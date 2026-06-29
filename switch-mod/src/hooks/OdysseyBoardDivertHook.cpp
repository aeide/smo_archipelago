// Odyssey "board -> Cap" divert — Devon's no-flight-map escape hatch (Cascade-only).
//
// The recurring free-travel softlock: the player flies the Odyssey from Cap into
// Cascade pre-equipped to grab one ability/capture, beats Madame Broode (always
// possible — her Chain Chomp is a fixed starter), collects her Multi-Moon... and
// then can't afford the rolled kingdom-gate moons to fly back out. Three attempts to
// open the takeoff gate all hit the inlining wall (findUnlockShineNum free-fn caught
// only labels; isUnlockedNextWorld absent from dynsym; member worker pending). See
// [[cap-return-and-cascade-arrival-demo]].
//
// Devon's idea instead: don't fight the gate — make boarding the Odyssey in Cascade
// behave like a subarea door that warps STRAIGHT to Cap, no flight map. From Cap
// (always peace'd, Odyssey present) the player flies onward normally. Scope chosen
// by Devon: Cascade post-Broode ONLY; every other kingdom keeps the vanilla map+gate.
//
// Mechanism (decomp-confirmed, OdysseyDecomp src/MapObj/ShineTowerRocket.h +
// src/System/GameDataFunction.cpp): the takeoff/world-map flow is the ShineTowerRocket
// actor. Two nerve states lead INTO the world-map UI — exeGoToWorldMapWithCamera and
// exeGoToWorldMapWithFade. We hook both: when standing in Cascade's home stage with
// Broode's Multi-Moon collected, we issue
// GameDataFunction::tryChangeNextStageWithDemoWorldWarp(writer, "CapWorldHomeStage")
// (the bare-stage-name Odyssey-flight commit, which picks Cap's own Odyssey-landing
// spawn — no entrance id needed) and SUPPRESS orig so the map camera never advances.
// Boarding therefore warps to Cap with no map. The internal changeNextStage it drives
// is caught by our existing EntranceShuffleHook, which floors Cap to its return
// layout + force-acquires the ship (capArrivalScenarioOverride / forceAcquireOdyssey).
//
// WHY this seam beats the gate hooks: nerve `exe` functions are dispatched indirectly
// through the nerve system, so the compiler cannot inline them — they always have a
// real out-of-line address. That's the opposite of the inlined predicates the gate
// approach kept missing. All three symbols are resolved via hk::ro::lookupSymbol with
// soft-degrade (NOT added to the sail .sym DB), so a missing symbol logs a warning at
// boot and leaves vanilla behavior rather than aborting module init — and the boot log
// doubles as the "is it really out-of-line" verification the decomp couldn't give.
//
// Trade-off (accepted with the Cascade-only scope): post-Broode, Cascade's Odyssey is
// a one-way Cap shuttle — you cannot pick another destination directly from Cascade
// (go via Cap). That is the intended escape-hatch behavior, not a bug.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdint>
#include <cstring>

namespace smoap::hooks {

// Defined in CascadeBroodeRespawnHook.cpp — true once Cascade's Madame Broode
// Multi-Moon is collected (Broode beaten). Pure save-state read.
bool cascadeMultiMoonCollected();

namespace {

struct GameDataHolderAccessor { void* mData; };
struct GameDataHolderWriter   { void* mData; };

using GetCurrentStageNameFn  = const char* (*)(GameDataHolderAccessor);
using TryDemoWorldWarpFn     = bool (*)(GameDataHolderWriter, const char*);

GetCurrentStageNameFn s_getCurrentStageName = nullptr;
TryDemoWorldWarpFn    s_tryDemoWorldWarp    = nullptr;

// Cascade's home stage — the only stage where Cascade's ShineTowerRocket exists.
constexpr const char* kCascadeHomeStage = "WaterfallWorldHomeStage";
constexpr const char* kCapHomeStage     = "CapWorldHomeStage";

const char* currentStageName() {
    if (!s_getCurrentStageName) return nullptr;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return nullptr;
    return s_getCurrentStageName(GameDataHolderAccessor{gdh});
}

// True when boarding should bounce straight to Cap: standing in Cascade's home stage
// AND Broode beaten. Both required — the ship actor exists in every kingdom, so the
// stage check is what scopes this to Cascade.
bool inCascadePostBroode() {
    const char* stage = currentStageName();
    if (!stage || std::strcmp(stage, kCascadeHomeStage) != 0) return false;
    return cascadeMultiMoonCollected();
}

// Issue the Cap warp once. Returns true if the divert was taken (caller must then
// suppress orig). false -> couldn't issue (fall through to vanilla map as a safe
// fallback so the actor is never left mid-nerve with nothing happening).
bool divertBoardingToCap(void* self, const char* which) {
    if (!inCascadePostBroode()) return false;
    if (!s_tryDemoWorldWarp) return false;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return false;

    // Fire the warp once per boarding actor; keep suppressing on subsequent frames
    // of the same nerve while the fade/stage-swap plays out.
    static void* s_warped_for = nullptr;
    if (s_warped_for == self) return true;
    s_tryDemoWorldWarp(GameDataHolderWriter{gdh}, kCapHomeStage);
    s_warped_for = self;
    SMOAP_LOG_INFO("[odyssey->cap] Cascade post-Broode boarding diverted to Cap "
                   "(no flight map) via %s -> %s", which, kCapHomeStage);
    return true;
}

HkTrampoline<void, void* /*ShineTowerRocket* this*/> goToWorldMapWithCameraHook =
    hk::hook::trampoline([](void* self) -> void {
        if (divertBoardingToCap(self, "exeGoToWorldMapWithCamera")) return;
        goToWorldMapWithCameraHook.orig(self);
    });

HkTrampoline<void, void* /*ShineTowerRocket* this*/> goToWorldMapWithFadeHook =
    hk::hook::trampoline([](void* self) -> void {
        if (divertBoardingToCap(self, "exeGoToWorldMapWithFade")) return;
        goToWorldMapWithFadeHook.orig(self);
    });

}  // namespace

void installOdysseyBoardDivertHook() {
    // Resolve the bare-stage-name warp commit we CALL (not hook).
    const ptr warp = hk::ro::lookupSymbol(
        smoap::sym::kGameDataFunctionTryChangeNextStageWithDemoWorldWarp);
    s_tryDemoWorldWarp =
        warp ? reinterpret_cast<TryDemoWorldWarpFn>(warp) : nullptr;

    const ptr stage =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionGetCurrentStageName);
    s_getCurrentStageName =
        stage ? reinterpret_cast<GetCurrentStageNameFn>(stage) : nullptr;

    if (!s_tryDemoWorldWarp || !s_getCurrentStageName) {
        SMOAP_LOG_WARN("[odyssey->cap] divert DISABLED — %s%slookup FAILED; Cascade "
                       "boarding keeps the vanilla flight map",
                       s_tryDemoWorldWarp ? "" : "tryChangeNextStageWithDemoWorldWarp ",
                       s_getCurrentStageName ? "" : "getCurrentStageName ");
        return;
    }

    const ptr cam = hk::ro::lookupSymbol(
        smoap::sym::kShineTowerRocketExeGoToWorldMapWithCamera);
    const ptr fade = hk::ro::lookupSymbol(
        smoap::sym::kShineTowerRocketExeGoToWorldMapWithFade);
    if (cam == 0 && fade == 0) {
        SMOAP_LOG_WARN("[odyssey->cap] divert DISABLED — neither "
                       "ShineTowerRocket::exeGoToWorldMapWith{Camera,Fade} resolved "
                       "(inlined/absent); Cascade boarding keeps the vanilla map");
        return;
    }
    SMOAP_LOG_INFO("installing OdysseyBoardDivertHook (Cascade post-Broode -> Cap, no "
                   "map) -> ShineTowerRocket::exeGoToWorldMapWithCamera @ 0x%lx + "
                   "WithFade @ 0x%lx",
                   static_cast<unsigned long>(cam),
                   static_cast<unsigned long>(fade));
    if (cam) goToWorldMapWithCameraHook.installAtPtr(cam);
    if (fade) goToWorldMapWithFadeHook.installAtPtr(fade);
}

}  // namespace smoap::hooks
