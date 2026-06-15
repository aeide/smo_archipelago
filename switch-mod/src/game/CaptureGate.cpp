// Capture lock + cap-name → bit-index mapping.
//
// Hakkun port: nn::ro::LookupSymbol → hk::ro::lookupSymbol; all other logic
// retained verbatim from production switch-mod.

#include "CaptureGate.hpp"

#include <cstring>

#include <hk/ro/RoUtil.h>

#include "../ap/ApState.hpp"
#include "../ap/capture_table.h"  // kCaptureNames, kCaptureHackNames
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"

struct GameDataHolderWriter   { void* mData; };
struct GameDataHolderAccessor { void* mData; };

namespace smoap::game {

namespace {

using AddHackDictionaryFn      = void (*)(GameDataHolderWriter, const char*);
using IsExistInHackDictionaryFn = bool (*)(GameDataHolderAccessor, const char*);

AddHackDictionaryFn       s_addHackDictionary       = nullptr;
IsExistInHackDictionaryFn s_isExistInHackDictionary = nullptr;

// Always-unlocked captures whose dict entries we pre-populate at scene load,
// independent of AP grants. Frog is the ONLY baseline capture: it's the very
// first capture in the game (needed to leave the Cap Kingdom opening area) and
// must be available before the AP item replay can arrive — otherwise a player
// who boots SMO before SMOClient/AP is connected would be ejected from the
// opening frog and soft-lock. (Frog is also a guaranteed precollected starter,
// so this is a belt-and-braces floor for the connection-timing window.)
//
// REMOVED (2026-06-14) — both are now real AP pool items that must be gated,
// not free:
//  - "ElectricWire" (Spark pylon): now gated on the "Spark pylon" item.
//    CORRECTION (2026-06-14, verified in-game): the forced Cap-Kingdom exit
//    pylon IS a real startHack capture (NOT a scripted cinematic, as an
//    earlier note assumed) — gating it soft-locked Mario inside Cap Kingdom.
//    Rather than make ALL Spark Pylons free (kBaselineHacks) we keep Spark
//    Pylon randomized and exempt ONLY the Cap-Kingdom instance via a
//    stage-scoped check in hooks/CaptureStartHook.cpp
//    (capIsExemptCapKingdomPylon: hack=="ElectricWire" && stage==
//    "CapWorldHomeStage"). So it stays OUT of kBaselineHacks here.
//  - "Koopa" (Bowser): now gated on the "Bowser" AP item.
inline constexpr std::array<std::string_view, 1> kBaselineHacks = {
    "Frog",
};

}  // namespace

std::uint8_t captureBitFor(const char* cap_name) {
    if (!cap_name) return 0xff;
    const std::size_t n = std::strlen(cap_name);
    for (std::uint8_t i = 0; i < kCaptureHackNames.size(); ++i) {
        const auto& sv = kCaptureHackNames[i];
        if (sv.size() == n && std::memcmp(cap_name, sv.data(), n) == 0) return i;
    }
    for (std::uint8_t i = 0; i < kCaptureNames.size(); ++i) {
        const auto& sv = kCaptureNames[i];
        if (sv.size() == n && std::memcmp(cap_name, sv.data(), n) == 0) return i;
    }
    for (const auto& alias : kCaptureHackAliases) {
        if (alias.hack_name.size() == n
            && std::memcmp(cap_name, alias.hack_name.data(), n) == 0) {
            return alias.bit;
        }
    }
    return 0xff;
}

bool captureBlocked(const char* cap_name) {
    const std::uint8_t bit = captureBitFor(cap_name);
    if (bit == 0xff) return false;
    return !smoap::ap::ApState::instance().captures_unlocked.test(bit);
}

std::string nameForHackData(/* const PlayerHackData* data */) {
    return {};
}

void playSE_NG() {
    SMOAP_LOG_INFO("playSE_NG (stub)");
}

void enumerateOwnedCaptures(CaptureEnumerationCallback cb, void* ctx) {
    if (!cb || !s_isExistInHackDictionary) {
        SMOAP_LOG_WARN("[snapshot] enumerateOwnedCaptures skipped: cb=%p sym=%p",
                       reinterpret_cast<void*>(cb),
                       reinterpret_cast<void*>(s_isExistInHackDictionary));
        return;
    }
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) {
        SMOAP_LOG_WARN("[snapshot] enumerateOwnedCaptures: GameDataHolder not cached yet");
        return;
    }
    GameDataHolderAccessor acc{gdh};
    int emitted = 0;
    for (const auto& sv : kCaptureHackNames) {
        if (sv.empty()) continue;
        const char* name = sv.data();
        if (s_isExistInHackDictionary(acc, name)) {
            cb(ctx, name);
            ++emitted;
        }
    }
    for (const auto& alias : kCaptureHackAliases) {
        if (alias.hack_name.empty()) continue;
        const char* name = alias.hack_name.data();
        if (s_isExistInHackDictionary(acc, name)) {
            cb(ctx, name);
            ++emitted;
        }
    }
    SMOAP_LOG_INFO("[snapshot] enumerateOwnedCaptures emitted=%d", emitted);
}

bool captureAlreadyInDictionary(const char* hack_name) {
    if (!hack_name || !*hack_name) return false;
    if (!s_isExistInHackDictionary) return false;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return false;
    GameDataHolderAccessor acc{gdh};
    return s_isExistInHackDictionary(acc, hack_name);
}

bool grantCapture(const char* cap_name, const char* hack_name) {
    if (!hack_name || !*hack_name) {
        SMOAP_LOG_WARN("[m6-capture] dropped: empty hack_name (cap='%s')",
                       cap_name ? cap_name : "");
        return false;
    }
    if (!s_addHackDictionary || !s_isExistInHackDictionary) {
        SMOAP_LOG_WARN("[m6-capture] dropped: symbols unresolved "
                       "(cap='%s' hack='%s')",
                       cap_name ? cap_name : "", hack_name);
        return false;
    }
    auto& st = smoap::ap::ApState::instance();
    if (!st.scene_cache.load(std::memory_order_relaxed)) {
        SMOAP_LOG_WARN("[m6-capture] dropped: scene not loaded yet "
                       "(cap='%s' hack='%s') — reconciler will retry",
                       cap_name ? cap_name : "", hack_name);
        return false;
    }
    void* gdh = st.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!gdh) {
        SMOAP_LOG_WARN("[m6-capture] dropped: GameDataHolder not cached yet "
                       "(cap='%s' hack='%s')",
                       cap_name ? cap_name : "", hack_name);
        return false;
    }
    GameDataHolderAccessor acc{gdh};
    if (s_isExistInHackDictionary(acc, hack_name)) {
        SMOAP_LOG_INFO("[m6-capture] already in dictionary cap='%s' hack='%s'",
                       cap_name ? cap_name : "", hack_name);
        return true;
    }
    GameDataHolderWriter w{gdh};
    SMOAP_LOG_INFO("[m6-capture] grantCapture firing cap='%s' hack='%s'",
                   cap_name ? cap_name : "", hack_name);
    s_addHackDictionary(w, hack_name);
    SMOAP_LOG_INFO("[m6-capture] addHackDictionary OK cap='%s' hack='%s'",
                   cap_name ? cap_name : "", hack_name);
    return true;
}

void reconcileCaptureDictionary() {
    auto& s = smoap::ap::ApState::instance();
    if (!s_addHackDictionary || !s_isExistInHackDictionary) return;
    if (!s.scene_cache.load(std::memory_order_relaxed)) return;
    void* gdh = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!gdh) return;

    GameDataHolderAccessor acc{gdh};
    GameDataHolderWriter   w{gdh};

    for (const auto& sv : kBaselineHacks) {
        if (sv.empty()) continue;
        const char* hack = sv.data();
        if (s_isExistInHackDictionary(acc, hack)) continue;
        SMOAP_LOG_INFO("[m6-capture] baseline pre-populate hack='%s'", hack);
        s_addHackDictionary(w, hack);
    }

    if (s.captures_unlocked.none()) return;

    for (std::uint8_t i = 0; i < kCaptureHackNames.size(); ++i) {
        if (!s.captures_unlocked.test(i)) continue;
        const auto& sv = kCaptureHackNames[i];
        if (sv.empty()) continue;
        const char* hack = sv.data();
        if (s_isExistInHackDictionary(acc, hack)) continue;
        SMOAP_LOG_INFO("[m6-capture] reconcile firing for bit=%u hack='%s'",
                       static_cast<unsigned>(i), hack);
        s_addHackDictionary(w, hack);
    }

    // Alias entries: ensure Lake-Puzzle / Goomba-PicMatch dict entries land
    // when the player owns the (single) AP item that gates both Nintendo
    // variants. Without this the Lake puzzle piece compendium slot stays
    // empty even after the AP grant.
    for (const auto& alias : kCaptureHackAliases) {
        if (!s.captures_unlocked.test(alias.bit)) continue;
        if (alias.hack_name.empty()) continue;
        const char* hack = alias.hack_name.data();
        if (s_isExistInHackDictionary(acc, hack)) continue;
        SMOAP_LOG_INFO("[m6-capture] reconcile alias firing for bit=%u hack='%s'",
                       static_cast<unsigned>(alias.bit), hack);
        s_addHackDictionary(w, hack);
    }
}

void installCaptureGrantSymbols() {
    ptr addr = hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionAddHackDictionary);
    if (addr == 0) {
        SMOAP_LOG_ERROR("addHackDictionary lookup FAILED");
    } else {
        s_addHackDictionary = reinterpret_cast<AddHackDictionaryFn>(addr);
        SMOAP_LOG_INFO("addHackDictionary resolved @ 0x%lx",
                       static_cast<unsigned long>(addr));
    }
    addr = hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionIsExistInHackDictionary);
    if (addr == 0) {
        SMOAP_LOG_ERROR("isExistInHackDictionary lookup FAILED");
    } else {
        s_isExistInHackDictionary = reinterpret_cast<IsExistInHackDictionaryFn>(addr);
        SMOAP_LOG_INFO("isExistInHackDictionary resolved @ 0x%lx",
                       static_cast<unsigned long>(addr));
    }
}

}  // namespace smoap::game
