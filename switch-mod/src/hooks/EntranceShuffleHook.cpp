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

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdint>
#include <cstring>

namespace smoap::hooks {

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
            fileChangeNextStageHook.orig(self, info, raceType);
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
