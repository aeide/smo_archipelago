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
#include "../game/CrossWorldLoad.hpp"
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
                                   const char* curStageName, const char* tag);

// Defined in CascadeBroodeRespawnHook.cpp. Returns the scenario to force the
// upcoming Cascade arrival to (so Madame Broode is placed) when committing into
// Cascade's home stage with her Multi-Moon uncollected, else -1. We write it into
// the ChangeStageInfo scenario field BEFORE orig — the engine's scenario-jump
// load input, which actually drives the load (the GameDataFile field write did not).
// Fires on any arrival whose ORIGIN is outside Cascade's world (kingdom-select
// flights, chain arrivals, the cabin — 2026-07-13 rescope after the B1
// retirement killed the old cabin-only trigger); Cascade-internal transitions
// get -1 so Cascade keeps its live scenario. The genuine prologue story drop
// (id 'start') is excluded at the call site below.
int cascadeArrivalScenarioOverride(void* gameDataFile, const char* destStageName,
                                   const char* curStageName);

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
inline constexpr const char* kMetroHomeStage     = "CityWorldHomeStage";
// New Donk City renders NIGHT during the Mechawiggler fight (main_scenario_no 1,
// where its Multi-Moon "New Donk City's Pest Problem" is placed); reaching Metro's
// overworld via a shuffled door / cross-kingdom subarea exit drops you into that
// night — wrong for a traversal hub. Force the immediately-post-Mechawiggler DAY
// city (scenario 3, the band-prep day state) on any arrival into CityWorldHomeStage that is NOT an Odyssey
// flight. Odyssey flights keep Metro's LIVE scenario, so the night Mechawiggler
// fight + its Multi-Moon stay reachable via the globe (Devon: reserve night for the
// Odyssey arrival). We deliberately do NOT jump to the festival (main_scenario_no 7)
// or the post-peace restored city (after_ending 5) — both too late; scenario 2 is a brief post-boss
// transition with no placed moons, so we use scenario 3 (the band-prep day city). Scenario numbers from shine_map.json main_scenario_no. Same lever as
// cascade/cap: ChangeStageInfo.mScenarioNo written before orig — a per-arrival LOAD
// input, NOT a persisted quest advance (Mechawiggler is never skipped; the stored
// story scenario is untouched, so a later Odyssey arrival is night again).
inline constexpr int         kMetroDayScenario   = 3;

// Returns kMetroDayScenario when an arrival into Metro's home stage should be forced
// to the day city (non-flight arrival, and only when RAISING toward day — never
// lowering a higher explicit scenario such as a moon-rock load at 8). Else -1 = leave
// the live scenario. curStageName == the Odyssey cabin means a globe flight -> keep
// night. incomingScenario is the ChangeStageInfo.mScenarioNo (-1/compute or a low
// night scenario are below kMetroDayScenario and get pulled up).
int metroDayArrivalScenarioOverride(const char* destStageName,
                                    const char* curStageName,
                                    int incomingScenario) {
    if (destStageName == nullptr) return -1;
    if (std::strcmp(destStageName, kMetroHomeStage) != 0) return -1;
    if (curStageName != nullptr &&
        std::strcmp(curStageName, kOdysseyInsideStage) == 0) return -1;  // flight
    if (incomingScenario >= kMetroDayScenario) return -1;  // never lower
    return kMetroDayScenario;
}

using GetCurrentStageNameFn = const char* (*)(GameDataHolderAccessor);
GetCurrentStageNameFn s_getCurrentStageName = nullptr;

// P5 §1.5-B1 — the bare-stage-name Odyssey-flight commit we CALL for remapped
// cross-world OVERWORLD targets (the native world-swap path; see
// routeRemappedCrossWorld). The looked-up address is patched by our own
// WorldMapSelectHook trampoline, so the call flows through it first — the
// chain_demo_warp_pending handshake keeps that trampoline's backstop/bounce
// out of the way. Resolved at install; nullptr degrades B1 to the B2 pre-arm.
using TryChangeDemoWarpFn = bool (*)(GameDataHolderWriter, const char*);
TryChangeDemoWarpFn s_tryChangeDemoWarp = nullptr;

// P5 §6.4 (Devon ruling): the Lost/Ruined normalization exemption is
// LIFTED. Lost lifts fully (its guard is the sweep's unlock skip, T2).
// Ruined stays story-managed ONLY pre-dragon: the Lord-of-Lightning
// fight must arm (the pinned progression Multi-Moon is earned there)
// and its vanilla completion repairs the ship — the in-game escape.
// Post-dragon (quest-recomputed scenario >= 2) chain arrivals normalize
// like everyone else. Scenario read unavailable (-1) => story-managed
// (fail toward vanilla behavior). Shared by processChainArrival +
// routeRemappedCrossWorld.
bool chainArrivalStoryManaged(const char* dest) {
    const bool ruined =
        std::strcmp(dest, "AttackWorldHomeStage") == 0 ||
        std::strcmp(dest, "BossRaidWorldHomeStage") == 0;
    if (!ruined) return false;
    const int w  = smoap::game::worldIdFromKingdomShort("Ruined");
    const int sc = smoap::game::scenarioNoForWorld(w);
    return sc < 2;
}

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
// landed 2026-06-19; P2 added the compound exit key 2026-07-07):
// processEntranceRemap passes dest/cur/transition_id to lookupEntranceRemap,
// which prefers an entry row matching `dest`, else an exit row matching
// (`cur`, transition_id) exactly, else an exit row matching `cur` with an
// empty from_id (wildcard) — and the same mutation body rewrites whichever
// hit. Coupled return-to-origin is handled two ways: exits that fire :file (changeNextStage
// with a ChangeStageInfo hardcoded to the vanilla parent overworld) get the
// exit-by-cur rewrite here; exits that fire :return (returnPrevStage, no info)
// pop back to wherever Mario came FROM, which under a rewritten forward entry is
// already the correct origin. Validated read-only via [entrance:remap-preview]
// across doors/pipes/multi-exit subareas/moon pipes (2026-06-19); the dest==cur
// guard skips moon-rock same-stage reloads.
static constexpr bool kEntranceRemapApply = true;

// ── B1 Odyssey-flight routing for cross-world OVERWORLD door hops (default OFF) ─
//
// Devon ruling 2026-07-12: the Odyssey flight cinematic must play ONLY when the
// player picks a kingdom on the in-cabin world-map (kingdom select) — NEVER on a
// door / subarea exit, even one that crosses into another kingdom. B1 (the
// tryChangeNextStageWithDemoWorldWarp reroute in routeRemappedCrossWorld) played
// that cinematic on cross-world OVERWORLD-target hops (e.g. a subarea exit landing
// on ForestWorldHomeStage flew into Wooded) AND dropped the marker id, so Mario
// landed at the Odyssey instead of the paired mouth.
//
// With this false, cross-world overworld targets take the SAME plain-commit +
// pre-arm + hold path as cross-world INTERIOR targets already did (the Luncheon
// 'GabuzouClockEx' exit in the 2026-07-11 walk: no flight, landed at the paired
// mouth, Odyssey parked by processChainArrival's forceAcquireOdyssey). Unblocked
// now that the T-A clobber fix (§10) makes plain cross-world commits crash-safe
// under pre-arm+hold — the §5.2 / §7.4 "ditch the B1 cinematic" change. Flip back
// to true to restore the flight-on-door-hop behavior.
static constexpr bool kB1DemoWarpCrossWorld = false;

// ── P0 decoupled-entrance-randomizer gate spike (approach A) ────────────────
// Hardcoded two-row test: does a subarea exit chained into a FOREIGN kingdom's
// door-mouth land Mario in a usable overworld state? No entrance_shuffle seed
// needed (the real remap table is empty), no new hooks, no new symbols — rides
// the same changeNextStage chokepoint as the coupled shuffle above. See
// docs/handoff-decoupled-p0-spike.md.
//
// RESULT: PASS (2026-07-06) — see docs/devon-p0-decoupled-spike-results.md.
// Flag left OFF; rows kept in place (harmless while false) as a documented,
// pre-verified fixture in case Phase 1+ work wants to re-run this exact probe.
static constexpr bool kP0DecoupledSpike = false;

// FixedSafeString<0x80> inline buffer capacity (incl. terminator). mStringTop
// (cstr ptr @ +0x08) points into this object-owned buffer, so a bounded,
// null-terminated overwrite is a safe in-place edit; sead stores capacity in
// mBufferSize and computes length on demand, so there is no length field to fix.
constexpr std::size_t kFixedStringCap = 0x80;

char* mutableCstrAt(ChangeStageInfo* info, std::size_t off) {
    auto* base = reinterpret_cast<std::uint8_t*>(info);
    return *reinterpret_cast<char* const*>(base + off);
}

// Shared bounded-mutation body for both the table-driven remap below and the
// P0 spike rows: verify BOTH strings fit before writing EITHER (never leave a
// torn rewrite — right stage / stale entrance id), then overwrite
// ChangeStageInfo's stage/id cstrs in place. `tag` names the caller for the
// APPLIED/FAILED log lines (e.g. "remap", "p0-spike"). Returns true iff the
// rewrite was applied (callers gate follow-up field edits on it).
bool applyEntranceMutation(const ChangeStageInfo* info, const char* dest,
                           const char* cur, const char* to_stage,
                           const char* to_id, const char* tag) {
    auto* mut       = const_cast<ChangeStageInfo*>(info);
    char* dst_stage = mutableCstrAt(mut, kOffChangeStageNameCstr);
    char* dst_id    = mutableCstrAt(mut, kOffChangeStageIdCstr);
    const std::size_t stage_len = std::strlen(to_stage);
    const std::size_t id_len    = std::strlen(to_id);
    if (!dst_stage || !dst_id ||
        stage_len + 1 > kFixedStringCap || id_len + 1 > kFixedStringCap) {
        SMOAP_LOG_WARN("[entrance:%s-FAILED] dest='%s' cur='%s' -> stage='%s' "
                       "id='%s' (buffer guard tripped) — left vanilla",
                       tag, dest, cur, to_stage, to_id);
        return false;
    }
    char old_id[smoap::ap::kCheckFieldCap];
    std::strncpy(old_id, readCstrAt(info, kOffChangeStageIdCstr),
                 smoap::ap::kCheckFieldCap - 1);
    old_id[smoap::ap::kCheckFieldCap - 1] = '\0';
    std::memcpy(dst_stage, to_stage, stage_len + 1);
    std::memcpy(dst_id, to_id, id_len + 1);
    SMOAP_LOG_INFO("[entrance:%s-APPLIED] dest='%s'/'%s' cur='%s' -> stage='%s' id='%s'",
                   tag, dest, old_id, cur, to_stage, to_id);
    return true;
}

// P4 crash fix (2026-07-08, [docs/handoff-p4-cascade-reentry-crash.md]):
// door-ENTRY ChangeStageInfos carry an explicit scenario=1 (correct for the
// vanilla subarea they were built for). When the remap redirects that commit
// to an overworld HomeStage, the stale 1 becomes the scenario-jump load input
// for a whole KINGDOM — and whenever the kingdom's live scenario is beyond 1
// (Broode beaten, moon rock open) the mismatched load pulls an inconsistent,
// oversized placement set and exhausts stage-load memory. Repro'd both ways:
// sead::FrameHeap abort on FileLoadThread (2026-07-07) and a NULL operator-new
// in the mod heap (2026-07-08); Devon's matrix pinned it to live-scenario!=1
// (R1 pre-Broode clean, R1/R3 post-Broode crash, R2 flight clean — flight
// recomputes the scenario). Fix: rewrite the scenario to -1, ChangeStageInfo's
// ctor default meaning "unspecified" — the engine then resolves the kingdom's
// live scenario exactly like every clean pipe-exit / P0-spike commit did.
// Scoped to remapped commits whose FINAL target is an overworld HomeStage;
// interior targets keep their scenario (Ex stages genuinely run scenario 1).
// The broode-respawn / cap-return overrides run AFTER this in the hook body
// and still force their scenarios when their own gates fire (cap-return's -1
// info-read path is designed for exactly this shape).
void neutralizeScenarioForOverworldTarget(const ChangeStageInfo* info,
                                          const char* to_stage) {
    if (!smoap::game::kingdomShortFromHomeStage(to_stage)) return;
    auto* scp = reinterpret_cast<std::int32_t*>(
        reinterpret_cast<std::uint8_t*>(const_cast<ChangeStageInfo*>(info))
        + kOffScenarioNo);
    if (*scp == -1) return;
    SMOAP_LOG_INFO("[entrance:remap-scenario] stale explicit scenario %d -> -1 "
                   "(engine recomputes live scenario for '%s')", *scp, to_stage);
    *scp = -1;
}

// Returns true iff a table row was APPLIED (the ChangeStageInfo was rewritten).
// The hook body uses this to run chain-arrival bookkeeping on remapped
// overworld commits only — never on vanilla transitions.
bool processEntranceRemap(const ChangeStageInfo* info) {
    if (!info) return false;
    const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
    if (!dest || dest[0] == '\0' || std::strcmp(dest, "(null)") == 0) return false;
    // getCurrentStageName — the EXIT key. We're leaving `cur`; an exit row keyed
    // on it rewrites the forward "exit pipe" dest to the origin door's overworld.
    const char* cur = currentStageName();
    // P2 — the transition's own id (mChangeStageId). At exit time this is the
    // shared ChangeStageId of the door pair Mario used (SMO convention), so it
    // disambiguates which of `cur`'s physical exits fired — the exact key
    // lookupEntranceRemap's compound-exit tier matches on.
    const char* transition_id = readCstrAt(info, kOffChangeStageIdCstr);
    // Moon-rock reload (and any self-transition) fires :file with dest == cur:
    // a scenario-jump reload of the SAME stage, never a door/exit. Skip it so we
    // don't remap a reload. (cur may be a sentinel like "(unresolved)" when
    // getCurrentStageName didn't resolve — that never equals a real dest, so the
    // guard is inert and we fall back to an entry-only lookup below.)
    if (cur && std::strcmp(dest, cur) == 0) return false;

    if constexpr (kP0DecoupledSpike) {
        const int scenario =
            *reinterpret_cast<const std::int32_t*>(
                reinterpret_cast<const std::uint8_t*>(info) + kOffScenarioNo);
        // Row 1 — the actual P0 test: leaving Push Block Peril (Cap, reachable
        // at game start; its exit pipes are proven to fire :file) lands outside
        // Luncheon's Crazy Cap shop — that door-mouth's primary_exit
        // (entrance_stages.json) is exactly where SMO places Mario walking out
        // of the shop, a known-good arrival point (approach A).
        if (cur && std::strcmp(cur, "PushBlockExStage") == 0) {
            SMOAP_LOG_INFO("[entrance:p0-spike] dest='%s' cur='%s' scenario=%d "
                           "-> stage='LavaWorldHomeStage' id='shop'",
                           dest, cur, scenario);
            applyEntranceMutation(info, dest, cur, "LavaWorldHomeStage", "shop",
                                 "p0-spike");
            return false;
        }
        // Row 2 — the return edge: walking into the Luncheon shop from this
        // chained port arrives back inside Push Block Peril, making it a true
        // undirected port edge (retrace works both ways).
        if (std::strcmp(dest, "LavaWorldShopStage") == 0) {
            SMOAP_LOG_INFO("[entrance:p0-spike] dest='%s' cur='%s' scenario=%d "
                           "-> stage='PushBlockExStage' id='PushBlockExStageEnt'",
                           dest, cur, scenario);
            applyEntranceMutation(info, dest, cur, "PushBlockExStage",
                                 "PushBlockExStageEnt", "p0-spike");
            return false;
        }
    }

    char to_stage[smoap::ap::kCheckFieldCap];
    char to_id[smoap::ap::kCheckFieldCap];
    if (!smoap::ap::ApState::instance().lookupEntranceRemap(dest, cur, transition_id,
                                                             to_stage, to_id))
        return false;

    if constexpr (!kEntranceRemapApply) {
        SMOAP_LOG_INFO("[entrance:remap-preview] dest='%s' cur='%s' -> stage='%s' "
                       "id='%s' (NOT YET APPLIED — kEntranceRemapApply is false)",
                       dest, cur, to_stage, to_id);
        return false;
    }

    if (!applyEntranceMutation(info, dest, cur, to_stage, to_id, "remap"))
        return false;
    neutralizeScenarioForOverworldTarget(info, to_stage);
    return true;
}

// ── P4 decoupled — chain-arrival bookkeeping + normalization ────────────────
//
// Runs on every REMAPPED commit whose FINAL target is an overworld HomeStage
// (a "chain arrival"). Two jobs, both pre-orig so the stage load reads them:
//
// 1. Bookkeeping for the chain-return flight scope (Devon ruling 2026-07-07:
//    from a chain-reached kingdom the Odyssey may fly to ALREADY-VISITED
//    kingdoms only): mark the destination chain-reached + visited, record the
//    chain ORIGIN (the kingdom Mario was last standing in — for interiors
//    that's still the kingdom containing them, via last_arrival_kingdom's
//    HomeStage-only updates), and mark the origin visited too (Mario is
//    demonstrably there; flight commits are the only other writers and the
//    starting kingdom never gets one).
//
// 2. Arrival normalization — the generalized Cascade treatment (Devon,
//    2026-07-08): setAlreadyGoWorld (parked flight landing instead of the
//    buried/one-time first-visit arrival flow) + forceAcquireOdyssey (ship
//    present + boardable; P0 Luncheon chain arrival had exist=0). Only fires
//    when the save hasn't already recorded a visit. P5 §6.4 (Devon ruling,
//    execution task T3): the Lost/Ruined normalization exemption is LIFTED.
//    Lost normalizes fully — its story guard is T2 (the softlock sweep
//    repairs the ship but never unlocks a chain-reached-only Lost). Ruined
//    stays story-managed ONLY pre-dragon (chainArrivalStoryManaged reads its
//    live scenario) so the Lord-of-Lightning fight still arms; post-dragon
//    Ruined chain arrivals normalize like everyone else.
//
// unlockWorld was REMOVED from this path (P4 finding 12, Devon ruling
// 2026-07-08): the watch item fired — decomp-confirmed that
// GameProgressData::unlockNextWorld is a monotonic SAVED counter, so
// unlocking a late chain kingdom permanently unlocked every earlier kingdom
// on the globe (and raised mHomeLevel). Globe listing for chain kingdoms is
// now the RAM-only force in OdysseyRescue::tickChainKingdomListing, and the
// "chain-reached-only" marker is save-derived (alreadyGo && !unlocked) — see
// docs/plan-p5-cross-world-loads.md §2.
void processChainArrival(GameDataFile* self, const char* dest,
                         const char* dest_kingdom) {
    if (!dest || !dest_kingdom) return;
    auto& st = smoap::ap::ApState::instance();

    const std::uint8_t dest_bit = smoap::game::kingdomBitFor(dest_kingdom);
    if (dest_bit >= 17) return;

    // Origin = the kingdom Mario was last standing in (frame-thread field,
    // updated only on HomeStage arrivals, so a chain fired from inside a
    // subarea still resolves to the subarea's parent kingdom).
    const std::uint8_t origin_bit =
        st.last_arrival_kingdom[0]
            ? smoap::game::kingdomBitFor(st.last_arrival_kingdom)
            : 0xff;

    const int world_id = smoap::game::worldIdFromKingdomShort(dest_kingdom);

    // 2026-07-09 walk fix: a chain door into a kingdom the player already
    // LEGITIMATELY unlocked must not brand it chain-reached — the session bit
    // fed the allowance + bounce and zeroed flight-visited Cascade's takeoff
    // gate ([chain-launch] ... orig=5 -> 0). Read-side has the same guard
    // (OdysseyRescue::isKingdomChainReachedOnly), this keeps ApState truthful.
    bool unlock_known = false;
    // Honest read (P5 T-C): if a prior tick force-listed this world, the raw
    // array reads unlocked — use the honest read so a re-entered chain kingdom
    // is still marked chain-reached (else its takeoff gate wouldn't zero).
    const bool legit_unlocked =
        smoap::game::isWorldUnlockedHonest(world_id, &unlock_known) && unlock_known;
    if (!legit_unlocked) st.markKingdomBitChainReached(dest_bit);
    st.markKingdomBitVisited(dest_bit);
    if (origin_bit < 17) {
        st.markKingdomBitVisited(origin_bit);
        st.chain_origin_bit[dest_bit].store(origin_bit, std::memory_order_relaxed);
    }

    const bool exempt = chainArrivalStoryManaged(dest);
    const bool already_go = smoap::game::isWorldAlreadyGo(world_id);

    SMOAP_LOG_INFO("[chain-arrival] dest=%s kingdom=%s bit=%u origin_bit=%u "
                   "worldId=%d alreadyGo=%d unlocked=%d storyManaged=%d",
                   dest, dest_kingdom, dest_bit, origin_bit, world_id,
                   already_go ? 1 : 0, legit_unlocked ? 1 : 0, exempt ? 1 : 0);

    if (exempt || already_go || world_id < 0) return;

    smoap::game::forceAlreadyVisitedWorld(self, world_id, "chain-arrival");
    smoap::game::forceAcquireOdyssey("chain-arrival");
}

// ── P5 §1.5 — cross-world routing for REMAPPED commits (B1 + B2 dispatch) ───
//
// Called only when processEntranceRemap APPLIED a row. Compares the FINAL
// target's world (WorldList::tryFindWorldIndexByStageName — resolves subareas
// too) against the currently RESIDENT world (the loader's, not GameDataFile's
// bookkeeping — residency is what the crash class depends on):
//
//   same world / unresolvable  → plain commit, untouched (vanilla shape).
//   cross, overworld, !exempt  → B1: re-route through
//       tryChangeNextStageWithDemoWorldWarp (the proven native swap path —
//       flights into Metro are consistently clean; §1.4). Returns true and
//       the caller SKIPS orig — the demo warp owns the commit. Accepted
//       costs (P5 doc): the marker id is lost (player lands at the Odyssey)
//       and the flight cinematic plays even for a door hop. Known probe
//       risks: demo-warp from inside a subarea, while airborne/captured.
//   cross, interior OR exempt  → B2: plain commit + arm the pre-load
//       (CrossWorldLoad fires it once the old scene is dead).
//
// Returns true iff the demo warp took the commit (caller must skip orig).
bool routeRemappedCrossWorld(const char* dest, const char* dest_kingdom) {
    const int dest_world = smoap::game::resolveWorldIdForStage(dest);
    const int resident   = smoap::game::residentWorldId();
    if (dest_world < 0 || resident < 0 || dest_world == resident) return false;

    const bool overworld = dest_kingdom != nullptr;
    if (kB1DemoWarpCrossWorld &&
        overworld && !chainArrivalStoryManaged(dest) && s_tryChangeDemoWarp) {
        void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
            std::memory_order_relaxed);
        if (holder) {
            SMOAP_LOG_INFO("[p5-b1] cross-world overworld commit '%s' "
                           "(world %d, resident %d) -> demo warp (native "
                           "world swap; marker id dropped)",
                           dest, dest_world, resident);
            smoap::ap::ApState::instance().chain_demo_warp_pending.store(
                true, std::memory_order_relaxed);
            if (s_tryChangeDemoWarp(GameDataHolderWriter{holder}, dest))
                return true;
            smoap::ap::ApState::instance().chain_demo_warp_pending.store(
                false, std::memory_order_relaxed);
            SMOAP_LOG_WARN("[p5-b1] demo warp REFUSED for '%s' — plain commit "
                           "+ pre-arm instead", dest);
        }
    }
    smoap::game::armCrossWorldPreload(dest_world, dest);
    return false;
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
    // Post-Broode for everyone; ALSO pre-Broode when the seed shipped
    // start_at_cap_peace (wire cap_peace_start). On such a seed the player
    // reaches Cascade with 0 checks (fly-in from the bootstrapped peace'd
    // Cap, Broode force keeps scenario 1) and the leave-gate blocks flying
    // out pre-Broode — the door divert is their only way back to Cap, so it
    // must not wait for the Multi-Moon. Trade-off unchanged: a diverted
    // boarding never opens the cabin (one-way Cap shuttle; fly onward from
    // Cap).
    if (!cascadeMultiMoonCollected() &&
        !smoap::ap::ApState::instance().cap_peace_start.load(
            std::memory_order_relaxed))
        return;

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

// ── First-visit door-arrival warp suppression (door-arrival-first-visit-demo) ─
//
// A REMAPPED (shuffled-door) FIRST arrival into a kingdom trips the game's
// first-visit forward-world-warp arrival flow: the Odyssey warp-in plays and
// Mario spawns AT THE ODYSSEY, overriding the paired door entrance id (Devon's
// Cascade->Metro shop->Sand). Decomp (GameDataFunction.cpp): isForwardWorldWarpDemo
// is only forward/backward DIRECTION (prev_index <= next_index in world-map
// order); the actual first-visit signal on a plain door commit is the STORED
// GameDataFile::isFirstTimeNextWorld() flag — which setAlreadyGoWorld does NOT
// touch, so processChainArrival's normalization never suppressed it (proven:
// alreadyGo set pre-orig, yet the original first visit still Odyssey-spawned).
//
// Fix (M7 "lie to the game", reversible): arm a short window at the remapped
// first-arrival commit (dest overworld HomeStage, not yet isAlreadyGoWorld), and
// the read-hook below returns false for isFirstTimeNextWorld while armed so the
// arrival takes the normal door-entrance path. No save write and NOT the
// mIsPlayDemoWorldWarp clear — avoids the 2026-07-05 mid-load-desync crash
// hazard (isFirstTimeNextWorld gates only the arrival PRESENTATION; the world
// load is driven by our own pre-arm/hold, independent of this flag). Self-disarms
// the instant the game clears its own first-time flag (orig goes false = arrival
// consumed it), so exactly ONE arrival is covered; a wallclock backstop matches
// the load hold timeout in case the flag is never read. Legit Odyssey world-map
// flights are demo-warp commits (not remapped) and never arm, so their intended
// first-visit intro + Odyssey spawn is untouched.
inline constexpr std::int64_t kFirstVisitWarpWindowMs = 30000;  // == kHoldTimeoutMs

// Read-through probe logger for the first-visit warp getters (measurement build,
// door-arrival-first-visit-demo). While the first-visit window is armed, log each
// candidate getter's live value the first time it's seen and on every change (per
// getter, capped). This is the DURING-LOAD read that both other sample points miss:
// the commit-time logWorldWarpDemoDiagNow fires before the destination scene has
// set these flags, and the 1 Hz post-arrival sweep fires after the scene init has
// consumed/reset them — the flags live only inside StageScene::init, between the
// two. It tells us (a) which flag the arrival reads TRUE, and (b) whether each
// getter is even called out-of-line during the load (ZERO lines for a getter over
// a known first-visit arrival = it's inlined at the scene-init consumer, so the
// free-function hook can't see it → attack the consumer/setter instead). READ-ONLY:
// never mutates, so it cannot desync the load or corrupt a save.
void logFirstVisitProbe(const char* name, bool val, int& last, int& count) {
    auto& st = smoap::ap::ApState::instance();
    const int armed =
        st.first_visit_warp_suppress_world.load(std::memory_order_relaxed);
    if (armed < 0) return;
    if (smoap::ap::ApState::nowMs() >=
        st.first_visit_warp_suppress_until_ms.load(std::memory_order_relaxed))
        return;  // window expired
    const int v = val ? 1 : 0;
    if (count > 0 && v == last) return;  // only the first call + value changes
    last = v;
    if (count < 40) {
        ++count;
        SMOAP_LOG_INFO("[first-visit-probe] %s=%d (armed world=%d) #%d", name, v,
                       armed, count);
    }
}

void armFirstVisitWarpSuppress(int dest_world, const char* dest) {
    if (dest_world < 0) return;
    auto& st = smoap::ap::ApState::instance();
    st.first_visit_warp_saw_true.store(false, std::memory_order_relaxed);
    st.first_visit_warp_suppress_until_ms.store(
        smoap::ap::ApState::nowMs() + kFirstVisitWarpWindowMs,
        std::memory_order_relaxed);
    st.first_visit_warp_suppress_world.store(dest_world, std::memory_order_relaxed);
    SMOAP_LOG_INFO("[first-visit-warp] ARMED world=%d dest='%s' (shuffled-door "
                   "first arrival; isFirstTimeNextWorld -> false until the arrival "
                   "consumes its flag, %lldms backstop)",
                   dest_world, dest ? dest : "?",
                   static_cast<long long>(kFirstVisitWarpWindowMs));
}

// isFirstTimeNextWorld(GameDataHolderAccessor) — the first-visit gate. Soft
// install (see installEntranceShuffleHook). While armed + within the window we
// force it false so the arrival uses the door entrance instead of the Odyssey
// warp-in; the moment the game's own flag clears (orig false) we disarm so the
// scope is a single arrival.
HkTrampoline<bool, GameDataHolderAccessor> isFirstTimeNextWorldHook =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> bool {
        const bool orig = isFirstTimeNextWorldHook.orig(acc);
        // Measurement: log EVERY call while armed (not just orig==true), so a
        // Wooded-style "no true->false" can be read as "called-but-false" vs.
        // "never called out-of-line" (inlined at the consumer).
        static int s_ftnw_last = -1, s_ftnw_count = 0;
        logFirstVisitProbe("isFirstTimeNextWorld", orig, s_ftnw_last, s_ftnw_count);
        auto& st = smoap::ap::ApState::instance();
        const int armed =
            st.first_visit_warp_suppress_world.load(std::memory_order_relaxed);
        if (armed < 0) return orig;
        const bool expired =
            smoap::ap::ApState::nowMs() >=
            st.first_visit_warp_suppress_until_ms.load(std::memory_order_relaxed);
        if (expired) {
            st.first_visit_warp_suppress_world.store(-1, std::memory_order_relaxed);
            if (orig)
                SMOAP_LOG_WARN("[first-visit-warp] window expired with flag still "
                               "set (world=%d) — passing through (Odyssey warp-in "
                               "may play)", armed);
            return orig;
        }
        if (orig) {
            // Flag is hot: latch it and suppress so the arrival uses the door.
            st.first_visit_warp_saw_true.store(true, std::memory_order_relaxed);
            static int s_log = 0;
            if (s_log < 20) {
                ++s_log;
                SMOAP_LOG_INFO("[first-visit-warp] isFirstTimeNextWorld true->false "
                               "(shuffled-door first arrival world=%d; use door "
                               "entrance, skip Odyssey warp-in) #%d", armed, s_log);
            }
            return false;
        }
        // orig == false: only disarm once the flag has been hot THEN cleared
        // (arrival consumed it). A false read BEFORE the flag was ever set (the
        // game sets it during the world load, after our commit-time arm) must not
        // disarm — else the real suppression read never happens. Until then this
        // is a pass-through no-op (orig is already false).
        if (st.first_visit_warp_saw_true.load(std::memory_order_relaxed))
            st.first_visit_warp_suppress_world.store(-1, std::memory_order_relaxed);
        return orig;
    });

// Read-through probes for the other three first-visit warp getters (measurement
// only — no suppression). isFirstTimeNextWorld was ruled out on the Wooded first
// visit (2026-07-12: ARMED fired but the flag never read true), so one of these —
// or a spawn path that reads none of them — drives the first-visit Odyssey
// placement. Soft-installed alongside the suppressor; each logs via
// logFirstVisitProbe while the first-visit window is armed.
HkTrampoline<bool, GameDataHolderAccessor> isForwardWorldWarpDemoProbe =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> bool {
        const bool orig = isForwardWorldWarpDemoProbe.orig(acc);
        static int last = -1, count = 0;
        logFirstVisitProbe("isForwardWorldWarpDemo", orig, last, count);
        return orig;
    });

HkTrampoline<bool, GameDataHolderAccessor> isPlayDemoWorldWarpProbe =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> bool {
        const bool orig = isPlayDemoWorldWarpProbe.orig(acc);
        static int last = -1, count = 0;
        logFirstVisitProbe("isPlayDemoWorldWarp", orig, last, count);
        return orig;
    });

HkTrampoline<bool, GameDataHolderAccessor> isEnterStageFirstProbe =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> bool {
        const bool orig = isEnterStageFirstProbe.orig(acc);
        static int last = -1, count = 0;
        logFirstVisitProbe("isEnterStageFirst", orig, last, count);
        return orig;
    });

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
            // P5: refresh the GameDataFile* cache (consumed by the drawMain
            // pump's chain-kingdom listing force — see ApState field docs).
            smoap::ap::ApState::instance().game_data_file_cache.store(
                self, std::memory_order_relaxed);
            logChangeStageInfo("file", info);
            const bool remapped = processEntranceRemap(info);
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
                // Capture the GENUINE first-visit state BEFORE processChainArrival
                // (its setAlreadyGoWorld write flips isWorldAlreadyGo). A remapped
                // door arrival into a kingdom Mario has never set foot in is the
                // one that trips the Odyssey warp-in — see armFirstVisitWarpSuppress.
                const int dest_world =
                    kingdom ? smoap::game::worldIdFromKingdomShort(kingdom) : -1;
                const bool first_visit_shuffled =
                    remapped && kingdom && dest_world >= 0 &&
                    !smoap::game::isWorldAlreadyGo(dest_world);
                // Chain-arrival bookkeeping + normalization MUST run before
                // reportArrival — it reads last_arrival_kingdom as the chain
                // ORIGIN, and reportArrival overwrites that with the dest.
                if (remapped && kingdom) processChainArrival(self, dest, kingdom);
                if (first_visit_shuffled) armFirstVisitWarpSuppress(dest_world, dest);
                // First-visit warp-demo VERIFICATION log (door-arrival-first-visit-
                // demo). The lever is now known — the stored isFirstTimeNextWorld
                // flag drives the shuffled-door first-arrival Odyssey warp-in, and
                // armFirstVisitWarpSuppress above suppresses it. This read-only line
                // stays as the walk check: on a GENUINE first arrival the preceding
                // [first-visit-warp] ARMED line should fire, then the isFirstTimeNext
                // true->false suppression, and Mario emerges from the door. (Note:
                // getCurrentWorldId is still the ORIGIN world at the commit, so the
                // firstNext/fwdWarpDemo fields here read the wrong world for door
                // hops; the alreadyGoWorld[] bitmap is the reliable per-world read.)
                if (kingdom && std::strcmp(dest, currentStageName()) != 0)
                    smoap::game::logWorldWarpDemoDiagNow("overworld-arrival");
                if (kingdom) smoap::ap::reportArrival(dest, kingdom);
                // P5 §1.5 — cross-world routing for remapped commits. B1
                // (demo-warp) returns true and OWNS the commit: skip orig and
                // every info-based override below (the abandoned info is
                // never consumed; the demo's own internal :file commit
                // re-enters this hook un-remapped and runs them normally).
                // B2 arms the pre-load and falls through to the plain orig.
                if (remapped && routeRemappedCrossWorld(dest, kingdom))
                    return;
                // Cascade/Broode respawn (PRIMARY): force the arrival scenario in
                // the ChangeStageInfo BEFORE orig consumes it, so the engine loads
                // Cascade directly in Broode's scenario (the scenario-jump input
                // moon rocks use). The post-orig GameDataFile field write below
                // fired but did NOT take (the load recomputes it), so this drives
                // the load instead. dest is the FINAL (post-remap) target.
                // currentStageName() = the stage we're leaving. The force fires on
                // any EXTERNAL-origin arrival (flight / chain arrival / cabin —
                // 2026-07-13 rescope, see CascadeBroodeRespawnHook); a Cascade
                // subarea return keeps the live scenario (Devon, 2026-07-05).
                // The genuine prologue story drop (id 'start') stays vanilla:
                // on non-cap-peace seeds its scenario is legitimately 1, and on
                // cap_peace_start seeds the peace'd drop with a boardable ship is
                // the intended divert flow. (With 'start' excluded here the H2
                // id rewrite below is unreachable on current flows — every
                // prologue visits Cascade, so post-prologue arrivals never carry
                // 'start'. Kept in case a future bootstrap skips the prologue.)
                const char* arrivalId = readCstrAt(info, kOffChangeStageIdCstr);
                const bool cascadeStoryDrop =
                    dest && arrivalId &&
                    std::strcmp(arrivalId, kCascadeStoryArrivalId) == 0 &&
                    std::strcmp(dest, kCascadeHomeStage) == 0;
                const int sc = cascadeStoryDrop ? -1 :
                    cascadeArrivalScenarioOverride(self, dest, currentStageName());
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

                // Metro "day city" on a non-flight arrival (see kMetroDayScenario).
                // A shuffled-door / cross-kingdom subarea exit into CityWorldHomeStage
                // lands in the NIGHT festival layout; force the DAY city instead.
                // Odyssey flights (cur == the cabin) are left alone, so the Festival
                // and its one night-gated Multi-Moon stay reachable via the globe.
                // Same lever as the Cap floor above: write ChangeStageInfo.mScenarioNo
                // before orig; never lowers a higher (moon-rock) scenario.
                {
                    auto* scp = reinterpret_cast<std::int32_t*>(
                        reinterpret_cast<std::uint8_t*>(const_cast<ChangeStageInfo*>(info))
                        + kOffScenarioNo);
                    const std::int32_t before = *scp;
                    const int metroSc = metroDayArrivalScenarioOverride(
                        dest, currentStageName(), before);
                    if (metroSc >= 0 && before != metroSc) {
                        *scp = metroSc;
                        SMOAP_LOG_INFO("[metro-day] changeNextStage force Metro "
                                       "arrival ChangeStageInfo.scenario %d -> %d "
                                       "(dest=%s, non-flight -> day city)",
                                       before, metroSc, dest);
                    }
                }
            }
            // Snapshot the ORIGIN stage before orig — post-orig currentStageName()
            // may already reflect the new stage, and the belt-and-braces force
            // below needs the departure stage (the Odyssey-cabin gate) to match
            // the pre-orig cascadeArrivalScenarioOverride check.
            char originStage[64];
            {
                const char* c = currentStageName();
                if (c) { std::strncpy(originStage, c, sizeof(originStage) - 1);
                         originStage[sizeof(originStage) - 1] = '\0'; }
                else   { originStage[0] = '\0'; }
            }
            fileChangeNextStageHook.orig(self, info, raceType);
            // Belt-and-braces: also re-assert the GameDataFile placement field
            // post-orig. It did NOT take alone (kept so the logs show both paths;
            // if the ChangeStageInfo write above succeeds this is redundant).
            // Same external-origin gate + story-drop exclusion as the pre-orig
            // force (the id is only H2-rewritten when the force fired, which the
            // story-drop exclusion prevents — so re-reading it here is stable).
            if (info) {
                const char* postDest = readCstrAt(info, kOffChangeStageNameCstr);
                const char* postId   = readCstrAt(info, kOffChangeStageIdCstr);
                const bool postStoryDrop =
                    postDest && postId &&
                    std::strcmp(postId, kCascadeStoryArrivalId) == 0 &&
                    std::strcmp(postDest, kCascadeHomeStage) == 0;
                if (!postStoryDrop)
                    forceCascadePlacementScenario(self, postDest, originStage,
                                                  "changeNextStage");
            }
        });

// [entrance:return] — GameDataFile::returnPrevStage(). Member function, no args.
// The separate exit path (no ChangeStageInfo).
HkTrampoline<void, GameDataFile*> returnPrevStageHook =
    hk::hook::trampoline([](GameDataFile* self) -> void {
        smoap::ap::ApState::instance().game_data_file_cache.store(
            self, std::memory_order_relaxed);
        SMOAP_LOG_INFO("[entrance:return] returnPrevStage cur='%s'",
                       currentStageName());
        returnPrevStageHook.orig(self);
    });

// ── P5 §1.6 read-only spike: which next-world read does the sequence consume?
//
// docs/plan-p5-cross-world-loads.md §1.3: GameDataFunction::calcNextWorldId =
// tryFindWorldIndexByMainStageName(getNextStageName()) resolves -1 for ANY
// subarea target — the decomp-confirmed mechanism of the foreign-world
// interior crash (Swinging Along the High-Rises). These two loggers tell the
// next walk (a) whether the engine reads either function out-of-line around a
// door commit, and (b) what it resolves per target class (door / flight /
// subarea). Soft installAtPtr (same pattern as MoonRockHook) — an inlined /
// absent symbol logs a miss and the walk falls back to lever 2 of §1.5-B2.
// Rate-limited on value change; these can fire per-frame.
HkTrampoline<int, GameDataHolderAccessor> calcNextWorldIdSpike =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> int {
        const int r = calcNextWorldIdSpike.orig(acc);
        static int s_last = -100;
        if (r != s_last) {
            s_last = r;
            SMOAP_LOG_INFO("[p5-nextworld] calcNextWorldId -> %d (cur='%s')",
                           r, currentStageName());
        }
        return r;
    });

HkTrampoline<int, GameDataHolderAccessor> getNextWorldIdSpike =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> int {
        const int r = getNextWorldIdSpike.orig(acc);
        static int s_last = -100;
        if (r != s_last) {
            s_last = r;
            SMOAP_LOG_INFO("[p5-nextworld] getNextWorldId -> %d (cur='%s')",
                           r, currentStageName());
        }
        return r;
    });

void installNextWorldIdSpike() {
    const ptr calcAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionCalcNextWorldId);
    if (calcAddr) {
        calcNextWorldIdSpike.installAtPtr(calcAddr);
        SMOAP_LOG_INFO("[p5-nextworld] calcNextWorldId spike @ 0x%lx",
                       static_cast<unsigned long>(calcAddr));
    } else {
        SMOAP_LOG_WARN("[p5-nextworld] calcNextWorldId lookup FAILED "
                       "(inlined/absent — §1.5-B2 lever 1 needs another read)");
    }
    const ptr getAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionGetNextWorldId);
    if (getAddr) {
        getNextWorldIdSpike.installAtPtr(getAddr);
        SMOAP_LOG_INFO("[p5-nextworld] getNextWorldId spike @ 0x%lx",
                       static_cast<unsigned long>(getAddr));
    } else {
        SMOAP_LOG_WARN("[p5-nextworld] getNextWorldId lookup FAILED "
                       "(inlined/absent)");
    }
}

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

    // First-visit door-arrival warp suppressor (see the trampoline header). Soft
    // install — isFirstTimeNextWorld is NOT in the sail .sym DB (OdysseyRescue
    // resolves it via lookupSymbol), so a miss must degrade, not abort.
    const ptr ftnwAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionIsFirstTimeNextWorld);
    if (ftnwAddr) {
        isFirstTimeNextWorldHook.installAtPtr(ftnwAddr);
        SMOAP_LOG_INFO("[first-visit-warp] isFirstTimeNextWorld suppressor @ 0x%lx",
                       static_cast<unsigned long>(ftnwAddr));
    } else {
        SMOAP_LOG_WARN("[first-visit-warp] isFirstTimeNextWorld lookup FAILED — "
                       "shuffled-door first-arrival Odyssey warp-in NOT suppressed");
    }

    // Read-through probes (measurement, door-arrival-first-visit-demo): log the
    // other three first-visit warp getters live during the next first-visit load,
    // to find which one (if any) the arrival reads TRUE. Soft-install each — a
    // miss just drops that one probe, never aborts.
    if (const ptr a =
            hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionIsForwardWorldWarpDemo)) {
        isForwardWorldWarpDemoProbe.installAtPtr(a);
        SMOAP_LOG_INFO("[first-visit-probe] isForwardWorldWarpDemo probe @ 0x%lx",
                       static_cast<unsigned long>(a));
    } else {
        SMOAP_LOG_WARN("[first-visit-probe] isForwardWorldWarpDemo lookup FAILED");
    }
    if (const ptr a =
            hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionIsPlayDemoWorldWarp)) {
        isPlayDemoWorldWarpProbe.installAtPtr(a);
        SMOAP_LOG_INFO("[first-visit-probe] isPlayDemoWorldWarp probe @ 0x%lx",
                       static_cast<unsigned long>(a));
    } else {
        SMOAP_LOG_WARN("[first-visit-probe] isPlayDemoWorldWarp lookup FAILED");
    }
    if (const ptr a =
            hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionIsEnterStageFirst)) {
        isEnterStageFirstProbe.installAtPtr(a);
        SMOAP_LOG_INFO("[first-visit-probe] isEnterStageFirst probe @ 0x%lx",
                       static_cast<unsigned long>(a));
    } else {
        SMOAP_LOG_WARN("[first-visit-probe] isEnterStageFirst lookup FAILED");
    }

    // P5 §1.6 next-world read spike (soft; see installNextWorldIdSpike).
    installNextWorldIdSpike();

    // P5 §1.5-B1 — resolve the demo-warp commit we CALL for remapped
    // cross-world overworld targets (soft; a miss degrades B1 to the B2
    // pre-arm, which covers every cross-world commit on its own).
    const ptr dwAddr = hk::ro::lookupSymbol(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithDemoWorldWarp);
    if (dwAddr) {
        s_tryChangeDemoWarp = reinterpret_cast<TryChangeDemoWarpFn>(dwAddr);
        SMOAP_LOG_INFO("[p5-b1] tryChangeNextStageWithDemoWorldWarp @ 0x%lx",
                       static_cast<unsigned long>(dwAddr));
    } else {
        SMOAP_LOG_WARN("[p5-b1] tryChangeNextStageWithDemoWorldWarp lookup "
                       "FAILED — B1 disabled, B2 pre-arm covers all "
                       "cross-world commits");
    }
}

}  // namespace smoap::hooks
