#include "ApState.hpp"

#include <cstring>

#include "nn/os.h"
#include "nn/os/os_tick.hpp"
#include "nn/time/time_timespan.hpp"

#include "../game/CaptureGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../game/MoonApply.hpp"
#include "../hooks/DeathHook.hpp"
#include "../util/Log.hpp"

class PlayerHitPointData;

namespace smoap::ap {

ApState& ApState::instance() {
    static ApState s;
    return s;
}

void ApState::applyOnFrame() {
    Item item;
    while (inbound.pop(item)) {
        Check synth{};
        synth.kind = item.kind;
        copyCheckField(synth.kingdom, item.kingdom.c_str());
        copyCheckField(synth.shine_id, item.shine_id.c_str());
        copyCheckField(synth.cap, item.cap.c_str());
        synth.slot = item.slot;
        const std::uint64_t h = hashCheck(synth);

        switch (item.kind) {
            case ItemKind::Moon:
                if (!item.kingdom.empty() && !item.shine_id.empty()) {
                    synthetic_grant_this_frame = true;
                    smoap::game::grantShine(item.kingdom, item.shine_id);
                    synthetic_grant_this_frame = false;
                    locations_checked.tryInsert(h);  // suppress matching outbound check
                }
                break;
            case ItemKind::Capture:
                if (!item.cap.empty()) {
                    const std::uint8_t bit = smoap::game::captureBitFor(item.cap);
                    if (bit < captures_unlocked.size()) captures_unlocked.set(bit);
                }
                break;
            case ItemKind::Kingdom:
                if (!item.kingdom.empty()) {
                    const std::uint8_t bit = smoap::game::kingdomBitFor(item.kingdom);
                    if (bit < 32) received_kingdom_mask |= (1u << bit);
                }
                break;
            case ItemKind::Shop:
            case ItemKind::Other:
                // M4 / M8: shop items don't grant in-game state directly; UI-only.
                break;
        }
    }
    synthetic_grant_this_frame = false;
    maybeApplyInboundKill();
}

std::int64_t ApState::nowMs() {
    // nn::os::GetSystemTick returns a u64 tick at a fixed ~19.2 MHz. Convert
    // via the SDK helper so we don't bake the rate in here.
    const auto ts = nn::os::ConvertToTimeSpan(nn::os::GetSystemTick());
    return static_cast<std::int64_t>(ts.GetMilliSeconds());
}

void ApState::maybeApplyInboundKill() {
    if (!inbound_kill_pending.exchange(false, std::memory_order_acq_rel)) return;
    if (!deathlink_enabled.load(std::memory_order_relaxed)) {
        SMOAP_LOG_INFO("[deathlink in] dropped (deathlink disabled in hello_ack)");
        return;
    }
    const auto now = nowMs();
    const auto last = last_observed_death_ms.load(std::memory_order_relaxed);
    if (last != 0 && now - last < kInboundKillDebounceMs) {
        SMOAP_LOG_INFO("[deathlink in] swallowed (last death %lldms ago < %lldms window)",
                       static_cast<long long>(now - last),
                       static_cast<long long>(kInboundKillDebounceMs));
        return;
    }
    auto* hp = static_cast<PlayerHitPointData*>(player_hp_cache.load(std::memory_order_relaxed));
    if (!hp) {
        // Chicken-and-egg: PlayerHitPointData::kill is the only callsite that
        // caches the pointer, so before Mario's first organic death we have
        // nothing to call. Drop with a log; subsequent inbound kills after his
        // first death will land.
        SMOAP_LOG_INFO("[deathlink in] dropped (no cached PlayerHitPointData yet)");
        return;
    }
    SMOAP_LOG_INFO("[deathlink in] applying synthetic kill");
    synthetic_death_this_frame = true;
    smoap::hooks::synthKillMario(hp);
    synthetic_death_this_frame = false;
    last_observed_death_ms.store(now, std::memory_order_relaxed);
}

std::uint64_t ApState::hashCheck(const Check& c) {
    // FNV-1a over a canonical fixed-order serialization. Cheap, no allocations.
    std::uint64_t h = 0xcbf29ce484222325ULL;
    auto mix = [&](const char* s) {
        for (; *s; ++s) {
            h ^= static_cast<std::uint8_t>(*s);
            h *= 0x100000001b3ULL;
        }
        h ^= '\x1f';
        h *= 0x100000001b3ULL;
    };
    h ^= static_cast<std::uint8_t>(c.kind);
    h *= 0x100000001b3ULL;
    mix(c.kingdom);
    mix(c.shine_id);
    mix(c.cap);
    h ^= static_cast<std::uint64_t>(c.slot + 1);  // -1 -> 0
    h *= 0x100000001b3ULL;
    // M4: fold the new raw fields so {stage_name, object_id} hashes uniquely.
    mix(c.stage_name);
    mix(c.object_id);
    h ^= static_cast<std::uint64_t>(c.shine_uid + 1);  // -1 -> 0
    h *= 0x100000001b3ULL;
    mix(c.hack_name);
    return h;
}

}  // namespace smoap::ap
