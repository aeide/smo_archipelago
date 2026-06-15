// ApState singleton + utility methods.

#include "ApState.hpp"

#include <hk/svc/api.h>
#include <hk/svc/cpu.h>

#include "../game/CaptureGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../hooks/DeathHook.hpp"
#include "../ui/CappyMessenger.hpp"
#include "../util/Log.hpp"
#include "../hooks/HookSymbols.hpp"
#include <hk/ro/RoUtil.h>
#include "../util/MsgFontSafe.hpp"

#include <cstdio>
#include <cstring>

class PlayerHitPointData;

namespace smoap::ap {

ApState& ApState::instance() {
    static ApState s;
    return s;
}

// Monotonic milliseconds. Switch system tick rate is 19.2 MHz (19200 ticks/ms).
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

namespace {

// Minimal layout mirror — same shape as AddPayShineHook's local. Keeps the
// game-side header bleed contained to one .cpp.
struct GameDataHolderAccessor { void* mData; };
using GetPayShineNumFn = int (*)(GameDataHolderAccessor, int);

}  // namespace

// Classify a moon item's grant amount. "X Kingdom Multi-Moon" represents
// one in-game Multi-Moon (3 power moons). All other moon items count as 1.
static int moonGrantAmount(const Item& item) {
    const char* s = item.shine_id;
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
    // Drain pending shine-color scouts first.
    ShineScout sc;
    while (inbound_scouts.pop(sc)) {
        if (sc.shine_uid < 0 ||
            static_cast<std::size_t>(sc.shine_uid) >= kMaxShineUid) {
            SMOAP_LOG_WARN("[shine-color] dropping uid=%d (out of range; bump kMaxShineUid?)",
                           sc.shine_uid);
            continue;
        }
        std::uint8_t pal = static_cast<std::uint8_t>(sc.palette & 0xFF);
        if (pal == kNoPaletteOverride) {
            pal = 0;
        }
        setShinePalette(sc.shine_uid, pal);
    }

    const bool suppress_cappy = (inbound.pendingApprox() > 3);

    constexpr std::size_t kDrainCap = 16;
    std::size_t drained = 0;
    while (drained < kDrainCap) {
        const Item* item_ptr = inbound.peekRef();
        if (!item_ptr) break;
        const Item& item = *item_ptr;
        Check synth{};
        synth.kind = item.kind;
        copyCheckField(synth.kingdom, item.kingdom);
        copyCheckField(synth.shine_id, item.shine_id);
        copyCheckField(synth.cap, item.cap);
        (void)hashCheck(synth);

        bool replay_suppress = false;

        switch (item.kind) {
            case ItemKind::Moon: {
                const int amount = moonGrantAmount(item);
                const std::uint8_t bit = item.kingdom[0]
                    ? smoap::game::kingdomBitFor(item.kingdom)
                    : 0xFFu;
                if (bit < 17) {
                    SMOAP_LOG_INFO(
                        "[m6-moon] grant observed kingdom=%s(bit=%u) +%d "
                        "shine_id='%s' from=%s (counter driven by OutstandingMsg)",
                        item.kingdom, bit, amount, item.shine_id, item.from);
                } else {
                    SMOAP_LOG_WARN(
                        "[m6-moon] DROPPED moon item: kingdom='%s' (bit=%u) "
                        "not a known kingdom — shine_id='%s' from=%s",
                        item.kingdom, bit, item.shine_id, item.from);
                }
                break;
            }
            case ItemKind::Capture:
                if (item.cap[0] != '\0') {
                    const std::uint8_t bit = smoap::game::captureBitFor(item.cap);
                    const char* hack = item.hack_name[0] ? item.hack_name : item.cap;
                    const bool already_owned =
                        smoap::game::captureAlreadyInDictionary(hack);
                    if (bit < captures_unlocked.size()) captures_unlocked.set(bit);
                    SMOAP_LOG_INFO("[m6-capture] cap='%s' bit=%u "
                                   "hack='%s' from=%s%s",
                                   item.cap, bit, item.hack_name, item.from,
                                   already_owned ? " (replay; suppressing bubble)" : "");
                    if (already_owned) {
                        replay_suppress = true;
                    } else {
                        const bool granted = smoap::game::grantCapture(item.cap, hack);
                        if (!granted) {
                            if (!pending_capture_grant.push(item)) {
                                SMOAP_LOG_WARN(
                                    "[m6-capture] pending_capture_grant FULL — "
                                    "dropping cap='%s' hack='%s'",
                                    item.cap, hack);
                            }
                            inbound.popDiscard();
                            ++drained;
                            continue;
                        }
                    }
                }
                break;
            case ItemKind::Other:
                SMOAP_LOG_DEBUG("[m6-other] item kind=%u name='%s' from=%s",
                                static_cast<unsigned>(item.kind),
                                item.name, item.from);
                break;
        }

        smoap::ui::CappyMessenger::instance().enqueue(item, local_slot,
                                                      suppress_cappy || replay_suppress);

        inbound.popDiscard();
        ++drained;
    }
    synthetic_grant_this_frame = false;
    maybeApplyInboundKill();
}

void ApState::flushPendingCaptureGrants() {
    // Silent early-out while prerequisites are missing — the per-frame retry
    // loop runs at draw-hook frequency, and grantCapture's WARN paths would
    // otherwise spam the log (~30/s) for every queued item across the entire
    // "waiting for the scene to load" window. The one-time WARN from the
    // initial applyOnFrame grant attempt is already enough signal that an
    // item is queued for retry.
    if (!scene_cache.load(std::memory_order_relaxed)) return;
    if (!game_data_holder_cache.load(std::memory_order_relaxed)) return;
    while (true) {
        const Item* item_ptr = pending_capture_grant.peekRef();
        if (!item_ptr) break;
        const Item& item = *item_ptr;
        const char* hack = item.hack_name[0] ? item.hack_name : item.cap;
        const bool granted = smoap::game::grantCapture(item.cap, hack);
        if (!granted) break;
        SMOAP_LOG_INFO("[m6-capture] deferred Cappy firing now cap='%s' "
                       "hack='%s' from=%s",
                       item.cap, hack, item.from);
        smoap::ui::CappyMessenger::instance().enqueue(item, local_slot,
                                                      /*suppress=*/false);
        pending_capture_grant.popDiscard();
    }
}

void ApState::applyCoinGrant() {
    // P1 — Cap Kingdom coin grant. Called on the frame thread once per draw.
    // Reads the pending cumulative total set by the worker thread on receipt
    // of a `coin_grant` wire message. Calls addCoin(delta) where
    // delta = total - coins_applied (high-water mark), so the same total
    // arriving twice is a no-op (idempotent pattern matching OutstandingMsg).
    //
    // Prerequisite: GameDataHolder must be cached (game_data_holder_cache) and
    // addCoin must be resolvable. If either is missing we log once and bail;
    // the next-frame retry will succeed after the scene loads.
    const int total = pending_coin_grant_total.load(std::memory_order_relaxed);
    if (total <= coins_applied) return;

    void* holder = game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder) {
        SMOAP_LOG_DEBUG("[p1-coins] applyCoinGrant deferred (no GameDataHolder yet)");
        return;
    }

    if (!add_coin_fn) {
        const auto addr = hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionAddCoin);
        if (!addr) {
            // Symbol absent from main.nso dynsym — soft-fail so the mod still
            // loads. Log once (next frames: total == coins_applied still fails
            // the guard above so we come back here but addr stays 0 until
            // fixed). Set coins_applied = total to silence the per-frame retry.
            SMOAP_LOG_WARN("[p1-coins] addCoin symbol not found in main.nso — "
                           "Cap coins will not be applied. Verify mangling and "
                           "rebuild with corrected SmoApSymbols.sym.");
            coins_applied = total;  // suppress repeated warn
            return;
        }
        add_coin_fn = reinterpret_cast<void*>(addr);
        SMOAP_LOG_INFO("[p1-coins] addCoin resolved @ 0x%lx", addr);
    }

    struct GameDataHolderWriter { void* mData; };
    using AddCoinFn = void (*)(GameDataHolderWriter, int);
    const auto fn = reinterpret_cast<AddCoinFn>(add_coin_fn);
    const int delta = total - coins_applied;
    fn(GameDataHolderWriter{holder}, delta);
    coins_applied = total;
    SMOAP_LOG_INFO("[p1-coins] addCoin delta=%d total=%d (coins_applied now %d)",
                   delta, total, coins_applied);
}

void ApState::applyAbilityState(const AbilityEntry* entries, std::size_t count) {
    // P3 — full-overwrite ability tracking. Worker thread only. Compares the
    // incoming counts against the prior table to decide which abilities are
    // newly unlocked / leveled, then overwrites the table under a seqlock.
    const std::size_t capped = (count < kAbilityTableMax) ? count : kAbilityTableMax;

    // Prior count for a name in the current (pre-overwrite) table; 0 if absent.
    auto priorCount = [this](const char* name) -> int {
        for (std::size_t i = 0; i < ability_table_count; ++i) {
            if (std::strcmp(ability_table[i].name, name) == 0)
                return ability_table[i].count;
        }
        return 0;
    };

    // Detect newly-unlocked / leveled abilities BEFORE overwriting so the
    // comparison is against the previous snapshot. Route bubbles through the
    // inbound_system_bubbles ring — direct CappyMessenger calls from the worker
    // thread crash Ryujinx's JIT (same reason as enqueueSystemBubble).
    for (std::size_t i = 0; i < capped; ++i) {
        const auto& e = entries[i];
        if (e.ability[0] == '\0') continue;
        if (e.count > priorCount(e.ability)) {
            SystemBubble bubble{};
            std::snprintf(bubble.text, sizeof(bubble.text), "Unlocked %s!", e.ability);
            if (!inbound_system_bubbles.push(bubble)) {
                SMOAP_LOG_WARN("[p3-ability] system bubble ring full; dropping "
                               "unlock bubble for '%s'", e.ability);
            }
            SMOAP_LOG_INFO("[p3-ability] unlocked/leveled '%s' count=%d "
                           "(was %d)", e.ability, e.count, priorCount(e.ability));
        }
    }

    // Seqlock full-overwrite (even=stable, odd=writing) — matches the
    // talkatoo_pools / shop_labels pattern so a P4 frame-thread reader can
    // re-read without a lock.
    const auto seq0 = ability_table_seq.load(std::memory_order_relaxed);
    ability_table_seq.store(seq0 + 1, std::memory_order_release);  // even -> odd
    for (std::size_t i = 0; i < capped; ++i) {
        std::memcpy(ability_table[i].name, entries[i].ability, kCheckFieldCap);
        ability_table[i].name[kCheckFieldCap - 1] = '\0';
        ability_table[i].count = entries[i].count;
    }
    ability_table_count = capped;
    ability_table_seq.store(seq0 + 2, std::memory_order_release);  // odd -> even
}

int ApState::abilityCount(const char* name) const {
    if (!name || !*name) return 0;
    // Seqlock read (matches applyAbilityState's even=stable/odd=writing).
    // Writes happen only on item receipt / HELLO replay (rare + brief), so a
    // few retries effectively always land on a stable snapshot. On the
    // pathological always-contended case we return the best-effort last read;
    // counts are monotonic so that can only under-report by a frame, never
    // over-grant a move the player doesn't own.
    int result = 0;
    for (int attempt = 0; attempt < 8; ++attempt) {
        const std::uint32_t s0 = ability_table_seq.load(std::memory_order_acquire);
        if (s0 & 1u) continue;  // writer mid-update
        result = 0;
        std::size_t n = ability_table_count;
        if (n > kAbilityTableMax) n = kAbilityTableMax;
        for (std::size_t i = 0; i < n; ++i) {
            if (std::strcmp(ability_table[i].name, name) == 0) {
                result = ability_table[i].count;
                break;
            }
        }
        const std::uint32_t s1 = ability_table_seq.load(std::memory_order_acquire);
        if (s0 == s1) return result;  // stable snapshot
    }
    return result;  // best-effort (contended)
}

bool ApState::abilityAtLeast(const char* name, int level) const {
    if (ability_gate_force_unlock.load(std::memory_order_relaxed)) return true;
    return abilityCount(name) >= level;
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
        SMOAP_LOG_INFO("[deathlink in] dropped (no cached PlayerHitPointData yet)");
        return;
    }
    SMOAP_LOG_INFO("[deathlink in] applying synthetic kill");
    synthetic_death_this_frame = true;
    smoap::hooks::synthKillMario(hp);
    synthetic_death_this_frame = false;
    last_observed_death_ms.store(now, std::memory_order_relaxed);
}

void ApState::setPendingMoonLabel(const char* text, int seq, std::int64_t deadline_ms) {
    if (seq <= 0) return;  // 0 is the "empty" sentinel
    std::size_t i = 0;
    if (text != nullptr) {
        while (i + 1 < kPendingMoonLabelCap && text[i] != '\0') {
            pending_moon_label.text[i] = text[i];
            ++i;
        }
    }
    pending_moon_label.text[i] = '\0';
    pending_moon_label.deadline_ms = deadline_ms;
    pending_moon_label.published_seq.store(seq, std::memory_order_release);
}

bool ApState::tryTakePendingMoonLabel(char (&text_out)[kPendingMoonLabelCap]) {
    const int seq = pending_moon_label.published_seq.load(std::memory_order_acquire);
    if (seq == 0) return false;
    if (seq == label_last_consumed_seq) return false;
    if (pending_moon_label.deadline_ms != 0 &&
        nowMs() > pending_moon_label.deadline_ms) {
        label_last_consumed_seq = seq;
        return false;
    }
    for (std::size_t i = 0; i < kPendingMoonLabelCap; ++i) {
        text_out[i] = pending_moon_label.text[i];
    }
    text_out[kPendingMoonLabelCap - 1] = '\0';
    label_last_consumed_seq = seq;
    return true;
}

void ApState::writeTalkatooKingdom(int bit,
                                   const char moons[][kCheckFieldCap],
                                   std::size_t count) {
    if (bit < 0 || static_cast<std::size_t>(bit) >= kTalkatooKingdomCount) {
        SMOAP_LOG_WARN("[talkatoo] writeTalkatooKingdom: bit=%d out of range; dropping",
                       bit);
        return;
    }
    auto& pool = talkatoo_pools[bit];
    // Seqlock: even=stable, odd=writing. Worker thread is the sole writer
    // (ApClient::handleLine -> here), but frame-thread readers
    // (TalkatooSpeechHook) load the count + entries inside a load-then-load
    // bracket and retry on torn reads.
    const auto seq0 = pool.seq.load(std::memory_order_relaxed);
    pool.seq.store(seq0 + 1, std::memory_order_release);  // even -> odd (writing)
    const std::size_t capped = (count < TalkatooKingdomPool::kMaxMoons)
        ? count : TalkatooKingdomPool::kMaxMoons;
    for (std::size_t i = 0; i < capped; ++i) {
        // moons[i] is a kCheckFieldCap char buffer; the source is bounded
        // by the wire parser. memcpy is safe — no allocator path.
        std::memcpy(pool.moons[i], moons[i], kCheckFieldCap);
        pool.moons[i][kCheckFieldCap - 1] = '\0';
    }
    // Zero the slot just past the last written entry so a stale longer pool
    // doesn't leak (the reader uses moon_count, but a defensive blank guard
    // helps debugging).
    if (capped < TalkatooKingdomPool::kMaxMoons) {
        pool.moons[capped][0] = '\0';
    }
    pool.moon_count = static_cast<std::uint8_t>(capped);
    pool.seq.store(seq0 + 2, std::memory_order_release);  // odd -> even (stable)
    // Enable the mode the first time any kingdom is written.
    talkatoo_mode.store(true, std::memory_order_release);
}

void ApState::clearTalkatoo() {
    // Disable mode FIRST so any concurrent reader sees "off" before we touch
    // the per-kingdom buffers (the speech hook gates on talkatoo_mode at the
    // entry point — once it's false, no further snapshots fire).
    talkatoo_mode.store(false, std::memory_order_release);
    for (auto& pool : talkatoo_pools) {
        const auto seq0 = pool.seq.load(std::memory_order_relaxed);
        pool.seq.store(seq0 + 1, std::memory_order_release);
        pool.moon_count = 0;
        // No need to wipe the name buffers — moon_count=0 makes them
        // unreachable, and a future writeTalkatooKingdom() overwrites in
        // place.
        pool.seq.store(seq0 + 2, std::memory_order_release);
    }
    // Phase 4: also clear named_moons. The block invariant only applies in
    // talkatoo_mode; clearing here means a future re-enable starts from a
    // clean slate (no carry-over named bits from a previous session).
    clearNamedMoons();
}

void ApState::markMoonNamed(int shine_uid) {
    if (shine_uid < 0) return;
    constexpr int kMaxBit = static_cast<int>(kNamedMoonsWordCount) * 64;
    if (shine_uid >= kMaxBit) return;
    const auto word_idx = static_cast<std::size_t>(shine_uid) / 64;
    const auto bit = static_cast<std::uint64_t>(1) << (shine_uid % 64);
    const auto prev = named_moons_bits[word_idx].fetch_or(bit, std::memory_order_relaxed);
    // Step 1a observability — track session-wide accumulation of named bits to
    // test the "isOpenShineName OR-in saturates the vanilla picker's pool"
    // hypothesis for the "No more hints now" flake. Only count NEW bits; a
    // re-named moon (idempotent visit) shouldn't bump the counter. Log every
    // 5th unique mark. Frame-thread only, no atomic-counter race in practice.
    if ((prev & bit) == 0) {
        static std::atomic<int> s_named_total{0};
        const int total = s_named_total.fetch_add(1, std::memory_order_relaxed) + 1;
        if ((total % 5) == 0) {
            SMOAP_LOG_INFO("[talkatoo-obs:1a] markMoonNamed total=%d "
                           "(this uid=%d)",
                           total, shine_uid);
        }
    }
}

bool ApState::isMoonNamed(int shine_uid) const {
    if (shine_uid < 0) return false;
    constexpr int kMaxBit = static_cast<int>(kNamedMoonsWordCount) * 64;
    if (shine_uid >= kMaxBit) return false;
    const auto word_idx = static_cast<std::size_t>(shine_uid) / 64;
    const auto bit = static_cast<std::uint64_t>(1) << (shine_uid % 64);
    return (named_moons_bits[word_idx].load(std::memory_order_relaxed) & bit) != 0;
}

void ApState::clearNamedMoons() {
    for (auto& w : named_moons_bits) {
        w.store(0, std::memory_order_relaxed);
    }
}

std::size_t ApState::snapshotTalkatooKingdom(
    int bit, char (*out_moons)[kCheckFieldCap], std::size_t out_cap) const {
    if (bit < 0 || static_cast<std::size_t>(bit) >= kTalkatooKingdomCount) return 0;
    if (!talkatoo_mode.load(std::memory_order_acquire)) return 0;
    const auto& pool = talkatoo_pools[bit];
    // Seqlock retry loop — bounded so a stuck writer doesn't hang the frame
    // thread. In practice the worker writes one kingdom in microseconds; a
    // single retry is enough.
    for (int attempt = 0; attempt < 3; ++attempt) {
        const auto s1 = pool.seq.load(std::memory_order_acquire);
        if (s1 & 1u) continue;  // writer mid-update
        const std::size_t n_read = pool.moon_count;
        const std::size_t n = (n_read < out_cap) ? n_read : out_cap;
        for (std::size_t i = 0; i < n; ++i) {
            std::memcpy(out_moons[i], pool.moons[i], kCheckFieldCap);
            out_moons[i][kCheckFieldCap - 1] = '\0';
        }
        const auto s2 = pool.seq.load(std::memory_order_acquire);
        if (s1 == s2) return n;
        // Torn read — writer interleaved. Try again.
    }
    return 0;
}

bool ApState::buildPaySnapshot(PendingPaySnapshot& out) const {
    void* holder = game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !get_pay_shine_num_fn) return false;
    auto fn = reinterpret_cast<GetPayShineNumFn>(get_pay_shine_num_fn);
    GameDataHolderAccessor acc{holder};
    // Iterate by kingdom BIT and resolve the matching worldId. Composition
    // (bit → short name → worldId) honors the Sea↔Snow swap documented on
    // kingdomBitForWorldId.
    for (int bit = 0; bit < 17; ++bit) {
        const char* name = smoap::game::kingdomForBit(static_cast<std::uint8_t>(bit));
        if (!name || !*name) {
            out.totals[bit] = 0;
            continue;
        }
        const int world_id = smoap::game::worldIdFromKingdomShort(name);
        if (world_id < 0) {
            out.totals[bit] = 0;
            continue;
        }
        const int n = fn(acc, world_id);
        out.totals[bit] = (n < 0) ? 0 : n;
    }
    return true;
}

namespace {

// Decode a single UTF-8 codepoint at `src[*pos]`. Advances `*pos` past the
// consumed bytes. Returns 0xFFFD on malformed input (and advances 1 byte to
// avoid infinite loops). Used by writeShopLabels to convert sanitized UTF-8
// labels into UTF-16 BMP codepoints for the patched shop hook.
std::uint32_t decodeOneUtf8(const char* src, std::size_t len, std::size_t* pos) {
    if (*pos >= len) return 0;
    const auto b0 = static_cast<std::uint8_t>(src[*pos]);
    if (b0 < 0x80) {
        ++(*pos);
        return b0;
    }
    auto consume_continuation = [&](std::size_t off, std::uint32_t* out) -> bool {
        if (*pos + off >= len) return false;
        const auto b = static_cast<std::uint8_t>(src[*pos + off]);
        if ((b & 0xC0) != 0x80) return false;
        *out = (*out << 6) | (b & 0x3F);
        return true;
    };
    std::uint32_t cp = 0;
    std::size_t nbytes = 0;
    if ((b0 & 0xE0) == 0xC0) { cp = b0 & 0x1F; nbytes = 2; }
    else if ((b0 & 0xF0) == 0xE0) { cp = b0 & 0x0F; nbytes = 3; }
    else if ((b0 & 0xF8) == 0xF0) { cp = b0 & 0x07; nbytes = 4; }
    else { ++(*pos); return 0xFFFD; }
    for (std::size_t i = 1; i < nbytes; ++i) {
        if (!consume_continuation(i, &cp)) { ++(*pos); return 0xFFFD; }
    }
    *pos += nbytes;
    return cp;
}

}  // namespace

void ApState::writeShopLabels(const ShopLabelEntry* entries, std::size_t count) {
    // Seqlock: even=stable, odd=writing. Frame-thread reader retries on
    // torn reads (lookupShopLabel). Worker thread is the sole writer.
    const auto seq0 = shop_label_seq.load(std::memory_order_relaxed);
    shop_label_seq.store(seq0 + 1, std::memory_order_release);  // even -> odd

    std::size_t written = 0;
    for (std::size_t i = 0; i < count && written < kShopLabelMax; ++i) {
        const auto& e = entries[i];
        // Skip empties — they could never match a hook call and silently
        // bloat the linear scan.
        if (e.file_name[0] == '\0' || e.key[0] == '\0') continue;

        auto& slot = shop_labels[written];
        std::memcpy(slot.file_name, e.file_name, sizeof(slot.file_name));
        slot.file_name[sizeof(slot.file_name) - 1] = '\0';
        std::memcpy(slot.key, e.key, sizeof(slot.key));
        slot.key[sizeof(slot.key) - 1] = '\0';

        // Sanitize via MsgFontSafe: maps the AP-server's UTF-8 (smart quotes,
        // em-dash, Latin-1 accents, ...) to the codepoints MessageFont38
        // actually ships. Result is still UTF-8 and ≤ source length in bytes.
        char sanitized[kShopLabelTextCap];
        const std::size_t san_len = smoap::util::sanitizeForMsgFont(
            e.label, sanitized, sizeof(sanitized));

        // UTF-8 → UTF-16 (BMP only; sanitize already collapsed astral
        // codepoints to ASCII). The hook returns char16_t* so this is the
        // wire-cap shape SMO expects from al::getSystemMessageString.
        std::size_t pos = 0;
        std::size_t u16 = 0;
        while (pos < san_len && u16 + 1 < kShopLabelTextCap) {
            const std::uint32_t cp = decodeOneUtf8(sanitized, san_len, &pos);
            if (cp == 0) break;
            // sanitizeForMsgFont's output covers BMP; surrogate-pair encoding
            // isn't reachable in practice. Clamp anything astral to '?' to be
            // defensive without bringing in surrogate-pair logic.
            slot.utf16[u16++] = (cp <= 0xFFFF) ? static_cast<char16_t>(cp)
                                               : static_cast<char16_t>('?');
        }
        slot.utf16[u16] = u'\0';
        slot.utf16_len = static_cast<std::uint16_t>(u16);
        ++written;
    }

    // Zero the slot just past the last written entry as a defensive guard so
    // a stale longer table can't leak via shop_label_count being wrong (the
    // reader uses shop_label_count, but a blank file_name still skips).
    if (written < kShopLabelMax) {
        shop_labels[written].file_name[0] = '\0';
        shop_labels[written].key[0] = '\0';
        shop_labels[written].utf16[0] = u'\0';
        shop_labels[written].utf16_len = 0;
    }
    shop_label_count = static_cast<std::uint16_t>(written);

    shop_label_seq.store(seq0 + 2, std::memory_order_release);  // odd -> even
}

const char16_t* ApState::lookupShopLabel(const char* file_name,
                                          const char* key) const {
    if (!file_name || !key) return nullptr;
    // Seqlock retry loop bounded so a stuck writer doesn't hang the frame
    // thread. The worker writes once per AP Connected / HELLO replay; under
    // normal play the lookup hits stable state on the first attempt.
    for (int attempt = 0; attempt < 3; ++attempt) {
        const auto s1 = shop_label_seq.load(std::memory_order_acquire);
        if (s1 & 1u) continue;  // mid-write
        const std::uint16_t n = shop_label_count;
        const char16_t* hit = nullptr;
        for (std::uint16_t i = 0; i < n && i < kShopLabelMax; ++i) {
            const auto& slot = shop_labels[i];
            if (slot.file_name[0] == '\0') continue;
            if (std::strcmp(slot.file_name, file_name) != 0) continue;
            if (std::strcmp(slot.key, key) != 0) continue;
            hit = slot.utf16;
            break;
        }
        const auto s2 = shop_label_seq.load(std::memory_order_acquire);
        if (s1 == s2) return hit;
        // Torn read — retry.
    }
    return nullptr;
}

}  // namespace smoap::ap
