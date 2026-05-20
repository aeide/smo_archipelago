// ApState singleton + utility methods.
//
// Phase 3b in progress. This file is being populated incrementally as the
// hooks that reference it land. Methods that aren't yet defined here will
// link if-and-only-if no current code path references them (LTO + gc-sections
// drop the unreferenced declarations).

#include "ApState.hpp"

#include <hk/svc/api.h>
#include <hk/svc/cpu.h>

namespace smoap::ap {

ApState& ApState::instance() {
    static ApState s;
    return s;
}

// Monotonic milliseconds. nn::os::GetSystemTick (used by the exlaunch build)
// returns u64 ticks at the system tick rate; Hakkun's hk::svc::getSystemTick
// is the equivalent. Switch's system tick rate is fixed at 19.2 MHz (1 ms ≈
// 19200 ticks); the conversion is ticks * 1000 / 19200000.
std::int64_t ApState::nowMs() {
    const u64 ticks = hk::svc::getSystemTick();
    return static_cast<std::int64_t>(ticks / 19200ULL);
}

// FNV-1a over a canonical fixed-order serialization. Cheap, no allocations.
// Used for session dedupe of outbound Check messages.
std::uint64_t ApState::hashCheck(const Check& c) {
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
    mix(c.stage_name);
    mix(c.object_id);
    h ^= static_cast<std::uint64_t>(c.shine_uid + 1);
    h *= 0x100000001b3ULL;
    mix(c.hack_name);
    return h;
}

}  // namespace smoap::ap
