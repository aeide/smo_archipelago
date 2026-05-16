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

// M6 phase A: classify a moon item's grant amount.
// "X Kingdom Multi-Moon" in the AP item pool represents one in-game Multi-Moon
// (3 power moons). All other moon items count as 1. Match on the shine_id
// suffix to keep this robust across "Multi-Moon", "Cap Kingdom Multi-Moon",
// etc. — the bridge passes only the kingdom-stripped tail in shine_id.
static int moonGrantAmount(const Item& item) {
    const char* s = item.shine_id.c_str();
    // Search for "Multi-Moon" substring (case-sensitive, deliberate — the
    // apworld emits exactly this casing).
    const char* needle = "Multi-Moon";
    while (*s) {
        const char* a = s;
        const char* b = needle;
        while (*a && *b && *a == *b) { ++a; ++b; }
        if (*b == '\0') return 3;
        ++s;
    }
    return 1;
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
        (void)h;  // M6 phase A: moon arm no longer dedupes via hash.

        switch (item.kind) {
            case ItemKind::Moon: {
                const int amount = moonGrantAmount(item);
                if (item.kingdom.empty()) {
                    // Truly generic "Power Moon" — only contributes to global.
                    const int prev = ap_moons_unkingdomed.fetch_add(amount,
                        std::memory_order_relaxed);
                    SMOAP_LOG_INFO(
                        "[m6-moon] credit unkingdomed +%d (was %d, now %d) "
                        "shine_id='%s' from=%s",
                        amount, prev, prev + amount,
                        item.shine_id.c_str(), item.from.c_str());
                } else {
                    const std::uint8_t bit = smoap::game::kingdomBitFor(item.kingdom);
                    if (bit < 17) {
                        const int prev = ap_moons_kingdom[bit].fetch_add(amount,
                            std::memory_order_relaxed);
                        SMOAP_LOG_INFO(
                            "[m6-moon] credit kingdom=%s(bit=%u) +%d "
                            "(was %d, now %d) shine_id='%s' from=%s",
                            item.kingdom.c_str(), bit, amount, prev,
                            prev + amount, item.shine_id.c_str(),
                            item.from.c_str());
                    } else {
                        // Unknown kingdom name — fall back to unkingdomed so
                        // the credit isn't silently dropped. Loud so we can
                        // patch kKingdoms / the bridge classifier.
                        const int prev = ap_moons_unkingdomed.fetch_add(amount,
                            std::memory_order_relaxed);
                        SMOAP_LOG_WARN(
                            "[m6-moon] UNKNOWN kingdom '%s' (bit=%u) — "
                            "credited to unkingdomed +%d (was %d, now %d) "
                            "shine_id='%s'",
                            item.kingdom.c_str(), bit, amount, prev,
                            prev + amount, item.shine_id.c_str());
                    }
                }
                break;
            }
            case ItemKind::Capture:
                if (!item.cap.empty()) {
                    const std::uint8_t bit = smoap::game::captureBitFor(item.cap);
                    if (bit < captures_unlocked.size()) captures_unlocked.set(bit);
                    SMOAP_LOG_INFO("[m6-capture] local-bit only (phase B "
                                   "lands hack-dictionary write): cap='%s' "
                                   "bit=%u from=%s",
                                   item.cap.c_str(), bit, item.from.c_str());
                }
                break;
            case ItemKind::Kingdom:
                if (!item.kingdom.empty()) {
                    const std::uint8_t bit = smoap::game::kingdomBitFor(item.kingdom);
                    if (bit < 32) received_kingdom_mask |= (1u << bit);
                    SMOAP_LOG_INFO("[m6-kingdom] local-bit only (phase C "
                                   "lands unlockWorld write): kingdom='%s' "
                                   "bit=%u from=%s",
                                   item.kingdom.c_str(), bit, item.from.c_str());
                }
                break;
            case ItemKind::Shop:
            case ItemKind::Other:
                SMOAP_LOG_DEBUG("[m6-other] item kind=%u name='%s' from=%s "
                                "(no in-game effect)",
                                static_cast<unsigned>(item.kind),
                                item.name.c_str(), item.from.c_str());
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
