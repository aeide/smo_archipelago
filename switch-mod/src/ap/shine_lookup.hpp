// Reverse lookups over the auto-generated shine_table.h.
//
// shine_table.h is the canonical (stage_name, obj_id, shine_uid, kingdom,
// shine_id_display_name) join. It's generated from apworld/.../locations.json
// + the per-machine shine_map.json by scripts/sync_shine_table.py — see the
// header at the top of shine_table.h for the format.
//
// This file adds three small lookups on top of that table:
//
//   - shine_uid_by_stage_obj(stage, obj)    : Phase 4 block hook input is
//     (stage, obj_id) read from a ShineInfo*. We need the shine_uid to index
//     the named_moons bitset.
//
//   - shine_uid_by_display_name(name)       : Phase 4 named-set publish path:
//     the substitute hook picks an AP-pool entry by display name string. We
//     need its shine_uid to add to the named_moons bitset.
//
//   - max_known_shine_uid                   : bitset-sizing constant. The
//     largest shine_uid in shine_table.h, hardened with a comfortable margin
//     for future apworld additions.
//
// All three are linear scans over the 436-row table. At ~10 calls per Talkatoo
// visit and ~50 ns per row, the overhead is negligible compared to a single
// log line. We deliberately don't sort + binary search — keeping the table
// generator dumb is more valuable than the microseconds.
//
// M6.1 allocator safety: no std::string / std::map. Inputs are `const char*`
// + string_view comparisons via memcmp.

#pragma once

#include <cstddef>
#include <cstring>
#include <string_view>

#include "shine_table.h"

namespace smoap::game {

// Returns the shine_uid for (stage_name, obj_id), or -1 if unknown. Both
// arguments may be nullptr; nullptr/empty → -1.
//
// Two callers today:
//   - Phase 4 block hook: read (stage, obj) from a Shine actor's ShineInfo
//     via ShineInfoLayout, resolve to shine_uid, check the bitset.
//   - Future: a build-time validator that checks shine_table.h vs ShineInfo
//     offsets at runtime via a known-uid sanity hit.
inline int shineUidByStageObj(const char* stage, const char* obj) {
    if (stage == nullptr || obj == nullptr) return -1;
    const std::string_view sv_stage{stage};
    const std::string_view sv_obj{obj};
    if (sv_stage.empty() || sv_obj.empty()) return -1;
    for (const auto& row : kShineTable) {
        if (row.stage_name == sv_stage && row.object_id == sv_obj) {
            return row.shine_uid;
        }
    }
    return -1;
}

// Returns the shine_uid for a display name like "Cascade Kingdom Timer
// Challenge 2", or -1 if not in the table. Names are USen ASCII; the
// substitute hook's chosen_ascii buffer is null-terminated and copied
// straight from the apworld's display strings, so comparison is byte-for-byte.
inline int shineUidByDisplayName(const char* display_name) {
    if (display_name == nullptr) return -1;
    const std::string_view sv{display_name};
    if (sv.empty()) return -1;
    for (const auto& row : kShineTable) {
        if (row.shine_id == sv) return row.shine_uid;
    }
    return -1;
}

// True if the moon identified by (stage_name, obj_id) is flagged
// `progression: true` in locations.json (a Multi Moon / boss-fight clear /
// scenario-advancing equivalent). Phase 4's Talkatoo% block calls this to
// skip the named-set check — scenario-advance moons must always be
// collectible or the player soft-locks on downstream moons that gate on
// scenario_no.
//
// Returns false for unknown (stage, obj) — fail-open. Unknown moons fall
// through the block's existing "shine_uid < 0 → vanilla" branch, so this
// "false default" is consistent with the existing not-in-shine-table semantic.
inline bool isProgressionShine(const char* stage, const char* obj) {
    if (stage == nullptr || obj == nullptr) return false;
    const std::string_view sv_stage{stage};
    const std::string_view sv_obj{obj};
    if (sv_stage.empty() || sv_obj.empty()) return false;
    for (const auto& row : kShineTable) {
        if (row.stage_name == sv_stage && row.object_id == sv_obj) {
            return row.progression;
        }
    }
    return false;
}

// Compile-time upper bound on shine_uid for sizing the named_moons bitset.
// As of 2026-05-20 the max shine_uid in the apworld is 1166 ("Lake Gardening:
// Spiky Passage Seed"). 2048 = nearest power-of-2 above with ~76% headroom.
// 2048 bits = 256 bytes / 32 u64 words.
inline constexpr int kMaxKnownShineUid = 2048;

}  // namespace smoap::game
