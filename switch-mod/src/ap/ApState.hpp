// Module-resident game-state mirror.
//
// Singleton accessed from two threads:
//   - Socket thread (ApClient::loop) — produces inbound items, consumes outbound.
//   - Frame thread (drawMain trampoline) — produces outbound checks, consumes inbound.
// All cross-thread state goes through SPSC ring buffers + std::atomic.

#pragma once

#include <array>
#include <atomic>
#include <bitset>
#include <cstdint>

#include "ApProtocol.hpp"

namespace smoap::ap {

// Allocation-free fixed-capacity open-addressing hash set used for session
// dedupe of location-check hashes. Originally shaped this way to dodge the
// M6.1 libstdc++/devkitA64 allocator hazard (std::set::insert reached for
// nn::os::GetTlsValue against an unallocated slot and NULL-derefed). The
// Hakkun cutover (LLVM libc++ + HeapSourceDynamic, 2026-05-21) lifted the
// constraint, but the set isn't on a critical hot path — checks fire at
// game-event rate, capped by N — so linear-probing keeps shipping.
//
// N must be a power of 2. With N = 4096 we get 32 KiB of storage and can
// hold up to ~3000 unique checks before probing degrades. Real seeds top out
// around 1000 locations.
template <std::size_t N>
class FlatHashSet {
    static_assert((N & (N - 1)) == 0, "N must be a power of 2");
public:
    // Returns true iff the value was newly inserted. Sentinel 0 is mapped to
    // 1 internally so callers can pass any 64-bit hash. Table-full returns
    // false (matches "already present" semantics — drops the check rather
    // than re-sending it).
    bool tryInsert(std::uint64_t h) {
        if (h == 0) h = 1;
        for (std::size_t i = 0; i < N; ++i) {
            const std::size_t idx = (h + i) & (N - 1);
            const std::uint64_t cur = slots_[idx];
            if (cur == 0) {
                slots_[idx] = h;
                ++size_;
                return true;
            }
            if (cur == h) return false;
        }
        return false;  // table full
    }

    void reset() {
        for (auto& s : slots_) s = 0;
        size_ = 0;
    }

    std::size_t size() const { return size_; }

private:
    std::uint64_t slots_[N] = {};
    std::size_t size_ = 0;
};

enum class ConnState : std::uint8_t {
    Disconnected = 0,
    Connecting = 1,
    Hello = 2,
    Ready = 3,
};

template <typename T, std::size_t N>
class SpscRing {
public:
    bool push(const T& v) {
        const auto h = head_.load(std::memory_order_relaxed);
        const auto next = (h + 1) % N;
        if (next == tail_.load(std::memory_order_acquire)) return false;  // full
        buf_[h] = v;
        head_.store(next, std::memory_order_release);
        return true;
    }
    bool pop(T& out) {
        const auto t = tail_.load(std::memory_order_relaxed);
        if (t == head_.load(std::memory_order_acquire)) return false;  // empty
        out = buf_[t];
        tail_.store((t + 1) % N, std::memory_order_release);
        return true;
    }
    // Peek at the front entry without consuming. Consumer-only (single
    // thread w.r.t. tail_). Used by pumpOnce for peek-then-pop sends:
    // a failing Send leaves the entry queued for the next pump cycle so
    // outbound checks survive transient socket errors / brief disconnects.
    bool peek(T& out) {
        const auto t = tail_.load(std::memory_order_relaxed);
        if (t == head_.load(std::memory_order_acquire)) return false;  // empty
        out = buf_[t];
        return true;
    }
    // Pointer to the front entry — zero copies. Use when T owns heap memory
    // (e.g. std::string fields) and copying it onto the consumer thread would
    // hit libstdc++'s allocator (which NULL-derefs in our subsdk9 link, see
    // memory project_libstdcpp_allocator_broken_in_subsdk9.md). Producer
    // still mutates buf_[head] freely; this returned pointer is invalidated
    // by popDiscard() but stable across pushes since tail_ doesn't move.
    const T* peekRef() {
        const auto t = tail_.load(std::memory_order_relaxed);
        if (t == head_.load(std::memory_order_acquire)) return nullptr;
        return &buf_[t];
    }
    // Discard the front entry. Caller must have observed it via peek().
    void popDiscard() {
        const auto t = tail_.load(std::memory_order_relaxed);
        tail_.store((t + 1) % N, std::memory_order_release);
    }
    // Approximate number of pending items. Two separate atomic loads, so the
    // value can race against a concurrent push (under-count by 1). For the
    // toast bulk-suppress heuristic this is fine — a borderline race resolves
    // to "suppressed = false" which is the safer default (toast might fire
    // for an item that arrived mid-frame; not a crash, just a visual quirk).
    std::size_t pendingApprox() const {
        const auto h = head_.load(std::memory_order_acquire);
        const auto t = tail_.load(std::memory_order_relaxed);
        return (h + N - t) % N;
    }

private:
    std::array<T, N> buf_{};
    std::atomic<std::size_t> head_{0};
    std::atomic<std::size_t> tail_{0};
};

struct StatusEvent {
    bool goal = false;
    bool death = false;
    std::int64_t ts_ms = 0;  // populated when death = true
};

// Inbound DeathLink debounce. Covers BOTH "Mario is currently in his death
// animation" and "two kills landed too close together". A single timestamp
// stamped on every observed death (organic or synthetic) is enough — if the
// last death was within this window, swallow.
inline constexpr std::int64_t kInboundKillDebounceMs = 15 * 1000;

// M6 phase A.5 — pending cutscene label slot.
//
// Single-slot publish-and-consume: socket thread (ApClient) writes the text +
// deadline, then release-stores `published_seq` to publish. Frame thread
// (MoonLabelHook callbacks) acquire-loads `published_seq`; if it differs from
// `last_consumed_seq`, reads the buffer and applies the label, then bumps
// `last_consumed_seq`. The release/acquire pair guarantees text-bytes ordering.
//
// `last_consumed_seq` is read/written only by the frame thread, so it doesn't
// need to be atomic. Same single-thread invariant holds for the buffer reads
// (consume side reads them once per cutscene; the socket thread won't
// overwrite while the cutscene is in flight unless a second moon is collected
// within the same ~3-5s window, in which case the newer label wins — which is
// what we want).
//
// Text buffer 32 bytes; bridge truncates to ≤30 bytes UTF-8 to leave room for
// the null terminator and a safety byte.
inline constexpr std::size_t kPendingMoonLabelCap = 32;

struct PendingMoonLabel {
    char text[kPendingMoonLabelCap] = {};
    std::int64_t deadline_ms = 0;     // monotonic; expired labels are dropped
    std::atomic<int> published_seq{0}; // 0 = empty / never set
};

class ApState {
public:
    static ApState& instance();

    std::atomic<ConnState> conn{ConnState::Disconnected};
    std::atomic<std::int64_t> last_rx_ns{0};

    // socket -> frame
    SpscRing<Item, 256> inbound;
    // frame -> socket
    SpscRing<Check, 256> outbound_checks;
    SpscRing<StatusEvent, 16> outbound_status;
    // frame -> socket. Overworld-arrival signal: when Mario enters a kingdom's
    // HomeStage (EntranceShuffleHook's changeNextStage commit), the frame
    // thread pushes the kingdom short name + dest stage here; ApClient drains
    // it into a StatusMsg the PC client uses to reveal that kingdom's rolled
    // exit threshold (randomize_kingdom_gates surprise). Deduped on the frame
    // thread by last_arrival_kingdom so re-entering an overworld from a subarea
    // doesn't re-emit. 16 slots is ample — arrivals are seconds apart.
    struct ArrivalEvent {
        char kingdom[32] = {};                 // apworld short name ("Sand")
        char stage_name[kCheckFieldCap] = {};  // dest HomeStage (informational)
    };
    SpscRing<ArrivalEvent, 16> outbound_arrivals;
    // Set by the socket worker on each hello_ack so the frame thread re-emits
    // the current kingdom's ArrivalEvent. The PC client resets reached_kingdoms
    // on every (re)connect, but last_arrival_kingdom (frame-thread dedup) lives
    // across the disconnect — without this resync a reconnect while standing in
    // a kingdom would leave that kingdom's rolled gate hidden forever. Consumed
    // (exchanged to false) by tickArrivalPoll on the frame thread.
    std::atomic<bool> arrival_resync{false};
    // any-thread -> socket. Mirror of every smoap::util::log() call above
    // SMOAP_LOG_FORWARD_MIN_LEVEL — surfaced in the PC client's "Switch" tab
    // so we can diagnose retail-Switch behaviour without `lm` capture.
    // SpscRing is single-producer; enqueueRemoteLog serialises producers
    // with its own atomic_flag spinlock since log() can be called from any
    // thread (frame, worker, hook callbacks).
    SpscRing<Log, 256> outbound_logs;
    std::atomic<std::uint32_t> log_drops{0};  // ring-full counter

    // socket -> frame. Pre-collection moon color: bridge sends
    // ShineScoutsMsg(s) once per AP connect after LocationScouts, then again
    // on every Switch HELLO. Each chunk holds up to ~200 (shine_uid, palette)
    // pairs. Frame thread drains and folds into shine_palette[].
    SpscRing<ShineScout, 4096> inbound_scouts;

    // socket -> frame. Hakkun build crashes Ryujinx's ARMeilleure JIT when
    // the worker thread directly calls CappyMessenger::enqueueSystem (non-
    // atomic writes to queue_[] from one thread while drawMain reads/writes
    // it from another). Production exlaunch survives the same race; we
    // don't. Route every worker-side system bubble through this ring and
    // have drawMain drain + enqueue from frame thread. 16 slots is plenty —
    // there are at most ~3-4 system bubbles in flight at any time.
    struct SystemBubble {
        char text[64];
    };
    SpscRing<SystemBubble, 16> inbound_system_bubbles;

    // frame-thread-only state below

    // Last kingdom we emitted an ArrivalEvent for. Frame-thread-only dedup so
    // reportArrival only enqueues on an actual kingdom change. Empty = none yet.
    char last_arrival_kingdom[32] = {};

    std::bitset<128> captures_unlocked;     // 43 used; index from capture_table.h
    FlatHashSet<4096> locations_checked;    // session dedupe (hash of message body)
    // Goal-once latch: CreditsStartHook (inline patch on StaffRollScene::init)
    // flips this true when the post-wedding credits roll starts — vanilla SMO
    // awards no moon for clearing the main game, and Mushroom-arrival
    // false-positives on the Luncheon portrait warp, so the credits scene is
    // the only no-false-positive signal. ApClient encodes this in state_chunk
    // meta so the bridge can suppress a stale snapshot re-fire on HELLO.
    // SaveLoadHook clears it on reload so a different save can re-trigger the
    // goal.
    bool goal_sent = false;
    bool synthetic_grant_this_frame = false;

    // M7: set immediately before we invoke the deferred capture-release
    // (PlayerHackKeeper::forceKillHack or tryEscapeHack) from the deferred-
    // kill tick. Defense-in-depth — today nothing observes the kill, but if
    // a future hook lands on the post-cancel path it can check this flag and
    // skip outbound reporting so we don't echo a synthetic "Mario un-captured"
    // event back to AP.
    bool synthetic_uncapture_this_frame = false;

    // ---- Talkatoo% mode --------------------------------------------------
    //
    // talkatoo_mode: bridge ships `talkatoo_pool` messages with enabled=false
    // to disable and enabled=true (one per kingdom) to enable. Acquire-loaded
    // by the speech hook on every Talkatoo interaction — release-stored after
    // any per-kingdom pool write so the consumer sees the data the moment it
    // sees the flag. Default false (vanilla Talkatoo).
    std::atomic<bool> talkatoo_mode{false};

    // Per-kingdom AP-pool of moon display names. Indexed by kingdomBitFor()
    // (0..16, matches ap_moons_kingdom[]). Worker thread (ApClient::handle
    // Line on receipt of a talkatoo_pool message) writes; frame thread
    // (TalkatooSpeechHook) reads. The seq counter is a classic seqlock:
    // even = stable, odd = mid-write. Worker increments to odd before
    // mutating, increments to even after. Frame-thread reader copies inside
    // a load-then-load pair and retries on mismatch / odd. Sized to absorb
    // the apworld's worst case (Sand has 62 moons today; cap 96 for growth).
    //
    // 17 × 96 × 64 = ~105 KiB BSS. Fixed buffers per the M6.1 allocator
    // contract.
    struct TalkatooKingdomPool {
        static constexpr std::size_t kMaxMoons = kTalkatooMaxMoonsPerKingdom;
        static constexpr std::size_t kNameCap = kCheckFieldCap;
        char moons[kMaxMoons][kNameCap] = {};
        std::uint8_t moon_count = 0;
        std::atomic<std::uint32_t> seq{0};
    };
    static constexpr std::size_t kTalkatooKingdomCount = 17;
    TalkatooKingdomPool talkatoo_pools[kTalkatooKingdomCount];

    // Worker-thread write — applies one kingdom's pool. Pass kCheckFieldCap-
    // sized name buffers; we copy up to `count` of them (capped at
    // kTalkatooMaxMoonsPerKingdom). Idempotent: re-writing the same kingdom
    // (HELLO replay across reconnects) just refreshes the buffer.
    void writeTalkatooKingdom(int bit,
                              const char moons[][kCheckFieldCap],
                              std::size_t count);

    // Worker-thread clear — resets all kingdoms to empty and flips
    // talkatoo_mode off. Called on a TalkatooPool message with enabled=false.
    void clearTalkatoo();

    // ---- Phase 4: named-moon set (collection block) -------------------------
    //
    // The substitute hook (TalkatooSpeechHook) calls `markMoonNamed(shine_uid)`
    // each time Talkatoo speaks a moon. The block path inside MoonGetHook calls
    // `isMoonNamed(shine_uid)` before letting Orig flip the shine flag; in
    // Talkatoo% mode, a moon that is NOT named is silently dropped — Mario's
    // get-cinematic plays but the shine bit never sets, AP credit is skipped,
    // and the moon respawns on save-reload (Option B / A3-fallback from the
    // roadmap).
    //
    // Storage: a 2048-bit bitset indexed by shine_uid (unique per moon across
    // all kingdoms in shine_table.h). 256 bytes BSS. No per-kingdom split
    // needed since shine_uid is globally unique.
    //
    // Threading: written from the frame thread inside TalkatooSpeechHook's
    // trampoline callback; read from the frame thread inside MoonGetHook's
    // callback. Both are the game thread; the atomic wrappers are belt-and-
    // braces for cross-frame visibility consistency with the other ApState
    // bit-vectors.
    //
    // Persistence: in-memory only for this iteration. A save+reload re-empties
    // named_moons (acceptable per the "must speak to Talkatoo first" invariant
    // — re-entering a kingdom means re-talking to Talkatoo to re-name moons).
    // A future iteration will mirror this state to the bridge via a new wire
    // message so the set survives game restarts within a single AP session.
    static constexpr std::size_t kNamedMoonsWordCount = 32;  // 32 * 64 = 2048
    std::atomic<std::uint64_t> named_moons_bits[kNamedMoonsWordCount];

    // Add a shine_uid to the named set. No-op for negative / out-of-range
    // uids (e.g. when the display name didn't resolve via shine_lookup).
    // Idempotent: re-naming the same moon is fine.
    void markMoonNamed(int shine_uid);

    // Query whether a shine_uid was named. Returns false for out-of-range
    // uids so the block hook fails-closed (unknown uid → blocked iff mode is
    // on, which means the moon isn't in shine_table.h at all — vanilla path).
    bool isMoonNamed(int shine_uid) const;

    // Reset the entire named set. Frame thread; called on disconnect /
    // talkatoo_mode-off transition.
    void clearNamedMoons();

    // Frame-thread read — snapshots one kingdom's pool into the caller-owned
    // arrays. Returns the count read (0 if the kingdom has no pool or the
    // bit is out of range). The seqlock retries internally up to a small
    // bound; a persistent torn read (writer stuck) returns 0.
    std::size_t snapshotTalkatooKingdom(int bit,
                                        char (*out_moons)[kCheckFieldCap],
                                        std::size_t out_cap) const;

    // ---- Shop moon labels ---------------------------------------------------
    //
    // ShopItemMessageHook patches two BLs inside `ShopLayoutInfo::updateItem
    // PartsData` (offsets 0x2089C4 and 0x208A44 in SMO 1.0.0 main.nso) that
    // would have called `al::getSystemMessageString(messageSystem, fileName,
    // key)`. The patched callback consults this table by (file_name, key);
    // on hit it returns a stowed UTF-16 string, on miss it falls through to
    // the original SDK lookup so the rest of the shop UI (costumes/
    // stickers/souvenirs) renders unchanged.
    //
    // Threading: worker thread writes via writeShopLabels (one
    // shop_labels wire message → full overwrite). Frame thread reads via
    // lookupShopLabel from the patched callback. Single-producer/
    // single-consumer seqlock — even=stable, odd=mid-write — matching the
    // talkatoo_pools pattern. The frame-thread reader returns nullptr on
    // torn read so the hook falls through to vanilla getSystemMessageString
    // rather than handing back garbage.
    //
    // Storage: each entry holds (file_name, key, utf16 buffer). The UTF-16
    // buffer is pre-sanitized via util::sanitizeForMsgFont then UTF-8 →
    // UTF-16 converted at write time so the hot path is a pointer return.
    //
    // Sizes: kShopLabelMax (32) × ~256 B per slot ≈ 8 KiB. Fixed buffers
    // per the M6.1 allocator-safety contract.
    struct ShopLabelSlot {
        char file_name[kCheckFieldCap] = {};
        char key[kCheckFieldCap] = {};
        // utf16 storage — sanitizeForMsgFont(label) decoded into UTF-16 with
        // a trailing 0. Length excludes the terminator.
        char16_t utf16[kShopLabelTextCap] = {};
        std::uint16_t utf16_len = 0;
    };
    ShopLabelSlot shop_labels[kShopLabelMax]{};
    std::uint16_t shop_label_count = 0;
    std::atomic<std::uint32_t> shop_label_seq{0};

    // Worker-thread write — full-overwrite the shop label table.
    // `count` is clamped to kShopLabelMax. Each (file_name, key, label_utf8)
    // tuple is normalized: label_utf8 is sanitized via
    // util::sanitizeForMsgFont then UTF-8 → UTF-16 converted. Empty file_name
    // or empty key entries are skipped (they could never match a hook call).
    // Idempotent: re-applying the same table is a no-op observable state.
    void writeShopLabels(const ShopLabelEntry* entries, std::size_t count);

    // Frame-thread read — linear scan for (file_name, key). Returns nullptr
    // on miss / torn read; on hit, returns a pointer to the stowed UTF-16
    // buffer (null-terminated). The pointer is stable for the lifetime of
    // the table (next writeShopLabels overwrites in place — a worker re-write
    // could change the returned bytes, but the seqlock retry bracket detects
    // this and the caller will simply fall through to vanilla).
    const char16_t* lookupShopLabel(const char* file_name, const char* key) const;

    // M7 deferred kill — CaptureStartHook's deny branch sets this instead of
    // calling the release inline; smoap::hooks::tickPendingUncapture() drains
    // it from drawMain after PlayerHackKeeper::isActiveHackStartDemo() returns
    // false (i.e. the capture-entry "dive in" cinematic has ended). The gate
    // serves two purposes:
    //   (1) firing inline from startHack is a no-op — the hack state machine
    //       hasn't fully entered the dive-in demo yet, so cancelHack /
    //       forceKillHack don't actually release Mario in that window
    //       (playtest 2026-05-16). Polling isActiveHackStartDemo per frame
    //       (matches KGamer77's SuperMarioOdysseyArchipelago Mod/source/main.cpp:73)
    //       catches the earliest safe moment.
    //   (2) it's funnier UX — the player runs around as the captured enemy
    //       for the duration of the dive-in cinematic before being yanked
    //       back to Mario.
    // Touched only from the frame thread (CaptureStartHook fires inline from
    // game code during frame processing, drawMain runs there too). Atomic
    // for paranoid cross-frame visibility / consistency with the surrounding
    // state fields.
    std::atomic<void*> pending_kill_keeper{nullptr};

    // Set by SaveLoadHook around Orig(initializeData) so the dictionary-
    // write filter (AddHackDictionaryHook) lets SMO rehydrate the
    // HackDictionary from save unconditionally. Without this, every
    // capture the player legitimately owned at save time would be
    // blocked by the filter (captures_unlocked is reset to all-zero
    // at the top of the SaveLoadHook callback, before bridge rehello)
    // and the dictionary would be silently truncated. Set/cleared on
    // the frame thread; read on the frame thread; atomic for the
    // release/acquire visibility guarantee.
    std::atomic<bool> save_load_passthrough{false};

    // Latched true the first time SaveLoadHook runs. Gates ApClient's
    // post-HELLO sendSnapshot so we don't enumerate GameDataHolder before
    // any save has been loaded — SMO's title screen populates GDH from
    // the last-used save file for the file-select previews, so a snapshot
    // taken at boot reports the previous save's moons/captures even if
    // the player is about to click "New Game". Bridge then forwards those
    // as fresh LocationChecks and AP credits them. SaveLoadHook fires for
    // both New Game and Load Save (both call GameDataFile::initializeData),
    // so the post-load re-HELLO ships the correct snapshot in either case.
    // Written on frame thread (SaveLoadHook); read on worker thread
    // (ApClient::threadMain) — atomic with release/acquire ordering.
    std::atomic<bool> save_was_loaded{false};

    // Cap name queued alongside the keeper. tickPendingUncapture re-reads
    // PlayerHackKeeper::getCurrentHackName(keeper) at deadline and compares
    // against this string. Mismatch (or empty) means SMO already released the
    // capture for some reason — player pressed Y, captured enemy died to the
    // environment (Bullet Bill against a wall, Goomba into lava), scene
    // transitioned, save loaded. Without this guard, forceKillHack/endHack
    // fires on a stale keeper bound to either nothing or a different cap.
    //
    // Frame-thread-only (CaptureStartHook deny writes, tickPendingUncapture
    // reads + clears) — no atomic required. char[64] not std::string for
    // the usual subsdk9 allocator-NULL-deref reason.
    char pending_kill_hack_name[64] = {};

    // M6 phase A — AP-credit counters surfaced via shine-counter hooks.
    // These are NOT shine flag flips: collecting a moon locally still drives
    // SMO's own shine table; AP-granted moons accumulate here and the
    // ShineNumGetHook / ShineNumByWorldGetHook add them on top of orig() so
    // the HUD reflects total credit. Reading these from the hook trampoline
    // (game thread) and writing from applyOnFrame (also game thread) — atomic
    // for paranoid cross-frame visibility only, no contention.
    //
    // kingdomBitFor() in KingdomUnlock.cpp returns 0..16 for known kingdoms;
    // ap_moons_kingdom[bit] is the per-kingdom credit count.
    std::atomic<int> ap_moons_kingdom[17] = {};

    // randomize_kingdom_gates — rolled Odyssey leave-thresholds, indexed by
    // kingdomBitFor() (0..16, same indexing as ap_moons_kingdom). -1 means
    // "vanilla" (UnlockShineNumHook passes through to orig). Worker thread
    // writes on receipt of a kingdom_gates message (full overwrite: reset
    // all slots to -1, then apply entries); frame-thread hook reads.
    // Plain per-slot atomics — each gate is independent, no cross-slot
    // consistency needed (a one-frame mixed view during overwrite is
    // harmless: every individual value is either old-valid or new-valid).
    std::atomic<int> kingdom_gate[17];

    void resetKingdomGates() {
        for (auto& g : kingdom_gate)
            g.store(-1, std::memory_order_relaxed);
    }

    // start_at_cap_peace slot flag (cap_peace_start wire msg, full-overwrite
    // on AP Connected + every HELLO replay). When true the fresh-save
    // Cap-peace bootstrap is re-armed: CapReturnScenarioHook bypasses its
    // vanilla-prologue guard (exiting Top Hat Tower floors Cap to the peace
    // layout + parks the Odyssey + unlocks Cascade), and EntranceShuffleHook's
    // Odyssey->Cap door divert fires even pre-Broode so a 0-check player can
    // leave Cascade. Boot default false = vanilla prologue (fail-safe for
    // option-off players and for play before the bridge connects). Worker
    // thread writes on receipt; frame-thread hooks read.
    std::atomic<bool> cap_peace_start{false};

    // ---- P7 entrance shuffle remap table -----------------------------------
    //
    // Bridge ships an `entrance_map` message (full-overwrite, possibly chunked)
    // resolving each vanilla door's destination stage to the shuffled interior.
    // EntranceShuffleHook reads this from the frame thread (inside
    // GameDataFile::changeNextStage) to rewrite the ChangeStageInfo target so
    // the door lands Mario in a different subarea than vanilla.
    //
    // Threading: the worker thread (ApClient::handleLine -> applyEntranceMap) is
    // the sole writer; the frame-thread hook reads via lookupEntranceRemap. The
    // seqlock (even=stable, odd=writing) matches the ability_table / shop_labels
    // pattern so the hook re-reads without a lock. A torn / contended read
    // returns "no remap" so the transition falls through to vanilla rather than
    // warping somewhere wrong — fail-safe, like the other lock-free readers.
    //
    // Holds BOTH directions: an entry row (is_exit=false) keyed by the inbound
    // dest stage, and an exit row (is_exit=true) keyed by the interior's own
    // stage (cur at exit time). Both directions share the pool of subarea
    // stages, so an entry key and an exit key can be the SAME string for
    // different transitions — merge/lookup must therefore key on
    // (from,from_id,is_exit), not from alone.
    //
    // P2 (decoupled entrance randomizer substrate): exit rows carry a second
    // match key, from_id — the transition's entry_id (SMO's mChangeStageId,
    // shared by both placements of a matched door pair). This disambiguates a
    // multi-exit stage's physical exits (e.g. Push Block Peril's door + pipe),
    // which previously both matched one wildcard cur-keyed row and could only
    // route to a single destination. Empty from_id = wildcard: matches any
    // transition id for that `from` stage, so every pre-P2 row (and every
    // coupled-shuffle row that doesn't need per-port routing) keeps working
    // unchanged.
    //
    // P3e (full port-involution substrate): entry rows now ALSO consult
    // from_id, same wildcard convention. Under a port matching two doors of
    // the SAME subarea can point at DIFFERENT partners, so entry rows sharing
    // `from` (the shared vanilla-dest interior stage) must disambiguate by
    // the door's own entry_id — mirrors the exit tiers exactly. Coupled-mode
    // entry rows keep shipping an empty from_id and hit the wildcard tier
    // unchanged (additive, no behavior change for existing seeds).
    //
    // P1 sized this for P3's full port-involution worst case (331-390 rows);
    // cap 512 with headroom. 512 slots x (4 x 64 + 1) ~= 128.5 KiB BSS. Fixed
    // buffers per the M6.1 allocator-safety contract.
    struct EntranceRemapSlot {
        char from[kCheckFieldCap] = {};       // match key (entry: dest; exit: cur)
        char from_id[kCheckFieldCap] = {};    // exit-only compound key: transition id
                                               // (mChangeStageId); empty = wildcard
        char to_stage[kCheckFieldCap] = {};   // rewrite dest stage
        char to_id[kCheckFieldCap] = {};      // rewrite arrival entrance id
        bool is_exit = false;                 // false=entry (dest key), true=exit (cur key)
    };
    static constexpr std::size_t kEntranceRemapMax = 512;
    EntranceRemapSlot entrance_remap[kEntranceRemapMax]{};
    std::size_t entrance_remap_count = 0;
    std::atomic<std::uint32_t> entrance_remap_seq{0};

    // Worker-thread write. `reset` clears the table before applying (first chunk
    // of a send); a follow-up chunk with reset=false merges by
    // (from,from_id,is_exit) (overwrites a matching slot, else appends).
    // Idempotent under HELLO replay.
    void applyEntranceMap(const EntranceRemapEntry* entries, std::size_t count,
                          bool reset);

    // Frame-thread read, two-key + compound entry/exit disambiguator. Match
    // precedence, first hit wins:
    //   1. ENTRY row matching (`dest_stage`, `transition_id`) exactly (P3e) —
    //      a specific physical door of a subarea with multiple doors.
    //   2. ENTRY row matching `dest_stage` with an empty from_id (wildcard) —
    //      the back-compat path every pre-P3e (incl. every coupled-shuffle)
    //      row still hits.
    //   3. EXIT row matching (`cur_stage`, `transition_id`) exactly (P2) — a
    //      specific physical exit port of a multi-exit stage.
    //   4. EXIT row matching `cur_stage` with an empty from_id (wildcard) —
    //      the back-compat path every pre-P2 row still hits.
    // On hit fills to_stage / to_id (null-terminated) and returns true.
    // Lock-free seqlock read; a torn / contended read returns false (vanilla).
    // `cur_stage` / `transition_id` may be null (caller couldn't resolve them)
    // — then only the entry key is tried.
    bool lookupEntranceRemap(const char* dest_stage,
                             const char* cur_stage,
                             const char* transition_id,
                             char (&to_stage)[kCheckFieldCap],
                             char (&to_id)[kCheckFieldCap]) const;

    // Worker-thread clear — empties the table (entrance_shuffle off / seed swap).
    void clearEntranceMap();

    // True while entrance shuffle is active for this seed — set when a non-empty
    // entrance_map is applied, cleared when the map is cleared. Mirrors the
    // entrance_remap table's lifecycle (so it's correct wherever that table is:
    // shuffle on/off, HELLO replay, seed swap) with no extra wire surface.
    // Read lock-free by CostumeDoorHook to gate the always-open costume doors
    // (Devon: costume doors unlock only when entrance shuffle is enabled).
    std::atomic<bool> entrance_shuffle_active{false};

    // M7 Path A — sticky "Mario has actually traveled to this kingdom"
    // bitmask, indexed by kingdomBitForWorldId (0..16). Populated ONLY from
    // stage-transition hooks (TryChangeDemoWorldWarp + TryChangeWorldWarpHole
    // in WorldMapSelectHook.cpp) — never from a per-frame poll. Save-data
    // load doesn't go through tryChangeNextStage, so a save-reload that puts
    // Mario back in Lake does NOT auto-set visited[Lake] (the previous
    // per-frame design did, which made the gate release prematurely on
    // testing setups with a pre-existing Lake save).
    //
    // Consumed by the KingdomOrderGate, which also OR-checks
    // "currentWorldId == prereq" to handle the load-into-prereq-kingdom case
    // without needing visited persistence: if Mario is sitting in Lake when
    // he opens the world map, the gate releases via the current-kingdom
    // branch even though visited[Lake] is false. Session-only — see the
    // gate's evaluateOrderGateForKingdom for the OR semantics.
    std::atomic<std::uint32_t> visited_kingdoms{0};

    bool isKingdomBitVisited(int bit) const {
        if (bit < 0 || bit >= 17) return false;
        return (visited_kingdoms.load(std::memory_order_relaxed) >> bit) & 1u;
    }

    void markKingdomBitVisited(int bit) {
        if (bit < 0 || bit >= 17) return;
        visited_kingdoms.fetch_or(1u << bit, std::memory_order_relaxed);
    }

    // ---- P4 decoupled — chain-return flight (Devon ruling 2026-07-07) ------
    //
    // Kingdoms reached through a REMAPPED overworld arrival (a port chain), as
    // opposed to an official Odyssey flight. Same bit indexing / session-only
    // semantics as visited_kingdoms. Set by EntranceShuffleHook's remap commit;
    // consumed by UnlockShineNumHook (open the takeoff gate while the rolled
    // leave-gate is unpaid) and WorldMapSelectHook (bounce not-yet-visited
    // flight picks back to the chain origin).
    std::atomic<std::uint32_t> chain_reached_kingdoms{0};

    bool isKingdomBitChainReached(int bit) const {
        if (bit < 0 || bit >= 17) return false;
        return (chain_reached_kingdoms.load(std::memory_order_relaxed) >> bit) & 1u;
    }

    void markKingdomBitChainReached(int bit) {
        if (bit < 0 || bit >= 17) return;
        chain_reached_kingdoms.fetch_or(1u << bit, std::memory_order_relaxed);
    }

    // P5 T-C (docs/plan-p5-cross-world-loads.md §9.3): worlds whose
    // GameProgressData::mIsUnlockWorld[w] RAM entry WE forced true in
    // OdysseyRescue::tickChainKingdomListing (needed so isExistHome derives a
    // boardable ship in a chain-reached-only locked kingdom, §8.1). That force
    // also poisons the engine's own unlock read: isWorldUnlockedRaw reads the
    // same array, so a forced world reads "legitimately unlocked" and the
    // chain-only derivation (allowance zeroing / visited-only bounce / Lost
    // guard) is neutered. Indexed by world id (0..16). Set by the listing
    // force; SUBTRACTED in isWorldUnlockedHonest so our own forces don't count
    // as legit unlocks; cleared wholesale by the GameDataFunction::unlockWorld
    // trampoline (a legit story unlock) and re-forced next tick for any world
    // still chain-only — self-healing, no story-order table.
    std::atomic<std::uint32_t> chain_unlock_forced_bits{0};

    bool isKingdomUnlockForced(int world_id) const {
        if (world_id < 0 || world_id >= 17) return false;
        return (chain_unlock_forced_bits.load(std::memory_order_relaxed) >>
                world_id) & 1u;
    }

    void markKingdomUnlockForced(int world_id) {
        if (world_id < 0 || world_id >= 17) return;
        chain_unlock_forced_bits.fetch_or(1u << world_id,
                                          std::memory_order_relaxed);
    }

    void clearAllKingdomUnlockForced() {
        chain_unlock_forced_bits.store(0, std::memory_order_relaxed);
    }

    // Per-kingdom chain ORIGIN — the kingdom Mario was last standing in when
    // the chain arrival committed (kingdomBitFor(last_arrival_kingdom) at the
    // remap seam). 0xff = unknown; the flight bounce falls back to Cap.
    // Written and read on the frame thread; atomics for ApState hygiene only.
    // Initialized to 0xff in the ctor (array NSDMI can't express the fill).
    std::atomic<std::uint8_t> chain_origin_bit[17];

    // The kingdom bit the chain-return takeoff allowance is CURRENTLY active
    // for, refreshed on every current-world findUnlockShineNum read (the same
    // read the launch check consumes, so the flight-commit bounce and the
    // launch decision can never disagree). 0xff = no allowance active.
    std::atomic<std::uint8_t> chain_allowance_bit{0xff};

    // P5 §1.5-B1 — one-shot handshake for the SYNTHETIC demo warp. Set by
    // EntranceShuffleHook immediately before it re-routes a remapped
    // cross-world overworld commit through
    // GameDataFunction::tryChangeNextStageWithDemoWorldWarp (whose address is
    // patched by our own WorldMapSelectHook trampoline, so the call lands
    // there first); consumed (exchange false) at the top of that trampoline
    // so the order-gate BACKSTOP and the chain-return visited-only bounce
    // never redirect the chain arrival that created them. Frame-thread only;
    // atomic for ApState hygiene.
    std::atomic<bool> chain_demo_warp_pending{false};

    // First-visit door-arrival warp-demo suppression (2026-07-12, door-arrival-
    // first-visit-demo). A REMAPPED (shuffled-door) first arrival into a kingdom
    // trips the game's first-visit forward-world-warp arrival flow: it plays the
    // Odyssey warp-in and spawns Mario AT THE ODYSSEY, overriding the paired door
    // entrance id — Devon's Cascade->Metro shop->Sand report. The gate is the
    // STORED GameDataFile::isFirstTimeNextWorld() flag (decomp: isForwardWorldWarpDemo
    // is only forward/backward DIRECTION; the first-visit signal on a plain door
    // commit is isFirstTimeNextWorld), which setAlreadyGoWorld does NOT touch — so
    // the existing chain-arrival normalization couldn't suppress it. Fix: arm this
    // window at the remapped first-arrival commit (dest overworld HomeStage, not
    // yet isAlreadyGoWorld), and the isFirstTimeNextWorld read-hook returns false
    // while armed so the arrival takes the normal door-entrance path. Reversible
    // (no save write) and NOT the mIsPlayDemoWorldWarp mid-load clear (avoids the
    // 2026-07-05 crash hazard). Scoped to shuffled-door arrivals ONLY: a legit
    // Odyssey world-map flight is a demo-warp commit (not remapped), never arms,
    // so its intended first-visit intro + Odyssey spawn is untouched.
    //   *_world = the destination world id (armed marker); -1 = disarmed.
    //   *_until_ms = wallclock backstop; the read-hook honors the window only
    //                while nowMs() < this.
    //   *_saw_true = latch: the read-hook only self-disarms once it has observed
    //                the game's own isFirstTimeNextWorld go TRUE (during the
    //                arrival) and then FALSE (arrival consumed it). Without the
    //                latch a stray pre-arrival read of a not-yet-set flag (false)
    //                would disarm prematurely — the flag can be set AFTER our
    //                commit-time arm, during the world load. Reset at each arm.
    std::atomic<int>          first_visit_warp_suppress_world{-1};
    std::atomic<std::int64_t> first_visit_warp_suppress_until_ms{0};
    std::atomic<bool>         first_visit_warp_saw_true{false};

    // M6 phase B — GameDataHolder pointer cache.
    //
    // DrawMainHook reads HakoniwaSequence::mGameDataHolder (offset 0xB8, a
    // GameDataHolderAccessor wrapping a GameDataHolder*) on every frame and
    // stores the GameDataHolder* here. CaptureGate::grantCapture (and the
    // upcoming phase C kingdom / snapshot enumerate paths) consume it to
    // construct GameDataHolderWriter / GameDataHolderAccessor wrappers for
    // GameDataFunction:: calls.
    //
    // Same thread on both sides (game frame thread); atomic only for the
    // visibility guarantee — matches the player_hp_cache pattern above.
    // Stored as void* to avoid leaking the game header here.
    std::atomic<void*> game_data_holder_cache{nullptr};

    // P5 chain-return hardening — GameDataFile* cache (the PLAYING file).
    // Refreshed by every GameDataFile hook that receives `this`:
    // changeNextStage + returnPrevStage (EntranceShuffleHook) and
    // initializeData (SaveLoadHook — fires on every save load, so a reload
    // can never leave this dangling on a stale file object). Consumed by
    // OdysseyRescue's chain-kingdom listing force, which reads
    // GameDataFile::mGameProgressData @ +0x6a8 off it from the drawMain pump
    // (see docs/plan-p5-cross-world-loads.md §2.3). Same thread + atomic
    // hygiene as game_data_holder_cache above.
    std::atomic<void*> game_data_file_cache{nullptr};

    // Metro "day city" placement force — pending target scenario.
    //
    // The visible Metro layout (festival stage / Pauline vs. band-prep day) is
    // placement-gated on GameDataFile::mScenarioNoPlacement (@0xb60), which the
    // load RECOMPUTES from global story progress each transition. Writing
    // ChangeStageInfo.mScenarioNo at the changeNextStage commit sets the
    // scenario-LOGIC number (drives resource load) but does NOT move the
    // placement field, so a globally-advanced save recomputes Metro to its
    // festival placement (7) even at scenario-logic 3 — the exit-into-festival
    // bug. Post-orig field writes at the commit "did NOT take" (recompute runs
    // after); the reliable seam is exeLoadStageHook PRE-orig (same place the
    // chain-kingdom unlock + cap-peace ship-acquire re-asserts land so placement
    // reads them). So EntranceShuffleHook's changeNextStage commit STASHES the
    // target here whenever metroDayArrivalScenarioOverride fires (non-flight
    // arrival into CityWorldHomeStage), and exeLoadStage consumes it once,
    // writing mScenarioNoPlacement before placement runs, then clears it (-1).
    // One-shot per commit: an Odyssey flight commit never sets it, so the night
    // Mechawiggler layout + its Multi-Moon stay reachable via the globe.
    //   >= 0 : force Metro's placement scenario to this value on the next load.
    //   -1   : nothing pending.
    std::atomic<int> metro_day_placement_scenario{-1};

    // AP-classification moon color (M-color milestone).
    // Indexed by SMO ShineInfo::shineId (s32). 0xFF = "no override; let the
    // game's stage color animation pick the default frame". Storage choice:
    // fixed array, NO std::map, to avoid the libstdc++ allocator NULL-deref
    // we hit in earlier milestones. 1 KiB BSS — cheap.
    //
    // Populated entirely on the frame thread by draining inbound_scouts in
    // applyOnFrame. Read on the frame thread by ShineAppearanceHook's
    // trampoline (single-threaded — both run inside drawMain or downstream).
    // Real shine_uid values observed in SMO 1.0.0 reach 1135+, so the original
    // 1024-cap was dropping ~half the moons. 2048 leaves ample headroom (2 KiB
    // BSS — still trivial) and stays a power of 2 for clarity.
    static constexpr std::size_t kMaxShineUid = 2048;
    static constexpr std::uint8_t kNoPaletteOverride = 0xFF;
    // Non-zero sentinel default: we want every uninitialized slot to mean
    // "no override" (let the game run orig() unchanged), not "use palette
    // frame 0" (an actual visible override). Filled to 0xFF in the ctor.
    std::uint8_t shine_palette[kMaxShineUid];

    // Bounds-checked accessors. Out-of-range uids return "no override" and
    // log once (the producer should never send these).
    std::uint8_t getShinePalette(int uid) const {
        if (uid < 0 || static_cast<std::size_t>(uid) >= kMaxShineUid) return kNoPaletteOverride;
        return shine_palette[uid];
    }
    void setShinePalette(int uid, std::uint8_t palette) {
        if (uid < 0 || static_cast<std::size_t>(uid) >= kMaxShineUid) return;
        shine_palette[uid] = palette;
    }

    // ---- Get-cutscene ("You got a Power Moon!") demo-model palette ----------
    //
    // The get cutscene holds up a SEPARATE demo-model actor (created by
    // Shine::addDemoModelActor), not the world Shine. That demo actor does NOT
    // carry the collected moon's mShineIdx, so resolving its palette off its own
    // bytes yields a fixed WRONG value (observed in-game: Luncheon / frame 6 on
    // every moon regardless of the granted kingdom). The AddDemoModelActor hook
    // records the SOURCE shine's already-correct granted palette here right
    // before the demo model is colored; the shine-color trampolines prefer this
    // for the brief window afterward so the held-up moon shows the granted
    // kingdom color instead of the bogus one. Game-thread only in practice, but
    // atomic to match the rest of ApState. get_demo_stamp_ms starts far in the
    // past so the window reads "inactive" until the first real collection.
    std::atomic<std::uint8_t> get_demo_palette{kNoPaletteOverride};
    std::atomic<std::int64_t> get_demo_stamp_ms{-1000000};

    void beginGetDemo(std::uint8_t palette) {
        get_demo_palette.store(palette, std::memory_order_relaxed);
        get_demo_stamp_ms.store(nowMs(), std::memory_order_relaxed);
    }
    // The granted palette to force onto shine-color calls landing within
    // `window_ms` of the last beginGetDemo(), or kNoPaletteOverride if the
    // window has lapsed or none was recorded.
    std::uint8_t activeGetDemoPalette(std::int64_t window_ms) const {
        const std::uint8_t pal = get_demo_palette.load(std::memory_order_relaxed);
        if (pal == kNoPaletteOverride) return kNoPaletteOverride;
        if (nowMs() - get_demo_stamp_ms.load(std::memory_order_relaxed) > window_ms)
            return kNoPaletteOverride;
        return pal;
    }

    // Monotonic ms of the last REAL moon collection (stamped by MoonGetHook).
    // The get-demo palette window above is only honored when a collection
    // landed this recently — Shine::showCurrentModel also fires (and latches a
    // palette) during ordinary stage loads, and without this gate that would
    // repaint on-screen world moons the collected moon's color. Starts far in
    // the past so nothing is "recent" until the first collection.
    std::atomic<std::int64_t> last_moon_get_ms{-1000000};

    void stampMoonGet() {
        last_moon_get_ms.store(nowMs(), std::memory_order_relaxed);
    }
    bool recentMoonGet(std::int64_t window_ms) const {
        return nowMs() - last_moon_get_ms.load(std::memory_order_relaxed)
               <= window_ms;
    }

    // DeathLink debounce. Set by the frame thread when PlayerHitPointData::kill
    // fires; cleared by the socket worker after the death message ships. A
    // second kill() within the same death event short-circuits.
    std::atomic<bool> death_pending_send{false};

    // ---- Inbound DeathLink (bridge -> mod) ----------------------------------
    //
    // Bridge sets deathlink_enabled in hello_ack so the user toggles DeathLink
    // in bridge config without rebuilding the mod. When false, inbound kill
    // messages are queued (in case the flag flips later) but never applied.
    std::atomic<bool> deathlink_enabled{false};

    // PlayerHitPointData* captured on every DeathHook fire so the frame thread
    // can call DeathHook::Orig with it later when applying an inbound kill.
    // Stored as void* to avoid leaking the game header into ApState.hpp.
    std::atomic<void*> player_hp_cache{nullptr};

    // Monotonic timestamp (ms) of the last observed death — organic OR our
    // own synthetic kill. The single source of truth for both "Mario currently
    // dead" and "too soon since last inbound kill" checks.
    std::atomic<std::int64_t> last_observed_death_ms{0};

    // Inbound queue collapsed to a single bit: closely-spaced bounces overwrite
    // each other → automatic producer-side debounce. Socket worker sets, frame
    // thread drains via exchange(false).
    std::atomic<bool> inbound_kill_pending{false};

    // Set by the frame thread immediately before invoking DeathHook::Orig on
    // a synthetic kill. Defense-in-depth: DeathHook's trampoline Orig already
    // bypasses our Callback, but a future hook anywhere downstream of
    // PlayerHitPointData::kill could re-enter — this flag lets the death path
    // recognize "we caused this" and short-circuit outbound reporting.
    bool synthetic_death_this_frame = false;

    // M6 phase A.5 — Channel A. Socket thread publishes via
    // setPendingMoonLabel(); frame thread (MoonLabelHook) consumes via
    // tryTakePendingMoonLabel().
    PendingMoonLabel pending_moon_label;
    int label_last_consumed_seq = 0;  // frame-thread only

    // Publish a new label. Producer side (socket thread).
    void setPendingMoonLabel(const char* text, int seq, std::int64_t deadline_ms);

    // Consume the pending label if there's a fresh, unexpired one. Returns
    // false if no fresh label, label expired, or already consumed this seq.
    // On success, fills `text_out` (null-terminated, ≤ kPendingMoonLabelCap)
    // and marks the seq consumed so subsequent calls are no-ops until a new
    // label arrives. Consumer side (frame thread).
    bool tryTakePendingMoonLabel(char (&text_out)[kPendingMoonLabelCap]);

    // Monotonic per-Switch-session counter that MoonGetHook stamps onto
    // outbound Check messages. Bridge echoes back in MoonLabelMsg.seq. Starts
    // at 1 so the wire encoder's "seq > 0 means present" check works.
    std::atomic<int> next_check_seq{1};

    // ---- M6 phase D — moon-deposit observation ------------------------------
    //
    // bridge_connected: set by ApClient::threadMain on HELLO ack, cleared on
    // disconnect/socket error. AddPayShineHook + ShineNumGetHook both read
    // this with relaxed ordering — neither needs synchronization with other
    // state, just an authoritative "are we online" bit.
    std::atomic<bool> bridge_connected{false};

    // get_current_world_id_fn: function pointer resolved via nn::ro::Lookup
    // Symbol at module init (same pattern as M6-B's addHackDictionary). Takes
    // a GameDataHolderAccessor by value (1 ptr in x0) and returns s32 world
    // id, clamped to 0 in develop states. Null until resolved.
    void* get_current_world_id_fn = nullptr;

    // get_pay_shine_num_fn: function pointer to
    // GameDataFunction::getPayShineNum(GameDataHolderAccessor, s32 worldId).
    // Resolved the same way (installPayShineSnapshotSymbol in KingdomUnlock.cpp).
    // Called from ApState::buildPaySnapshot in the AddPayShineHook tail / the
    // worker's HELLO snapshot path. Null until resolved.
    void* get_pay_shine_num_fn = nullptr;

    // Snapshot of per-kingdom PayShineNum awaiting transmission to the
    // bridge. The frame thread (AddPayShineHook tail) builds via
    // buildPaySnapshot and pushes; the worker drains in pumpOnce. The
    // bridge derives outstanding = lifetime_received_AP − PayShineNum, so
    // a save crash that rolls back PayShineNum naturally rebounds the
    // outstanding on the next snapshot. Ring size 4 with last-snapshot-
    // wins semantics — every snapshot is a complete reading, so coalescing
    // is safe (and desirable: spaced-too-close tosses don't backpressure).
    struct PendingPaySnapshot {
        int totals[17] = {};      // index = kingdomBit
    };
    SpscRing<PendingPaySnapshot, 4> pending_pay_snapshots;

    // Populate `out.totals[0..16]` from the live GameDataHolder. Returns
    // false if GameDataHolder isn't cached yet (title screen pre-save-load)
    // or the symbol failed to resolve — caller skips push.
    bool buildPaySnapshot(PendingPaySnapshot& out) const;

    // P1 — Cap Kingdom coin grant.
    //
    // Bridge sends `coin_grant` with a cumulative lifetime total (Cap moons
    // received x 100 coins each). The worker thread stores it here; the frame
    // thread reads it in applyCoinGrant() and calls addCoin(delta).
    //
    // pending_coin_grant_total: written by worker, read by frame thread.
    // pending_coin_baseline: coins already applied to this save (client-
    //   persisted per seed+slot). Written by worker; applyCoinGrant seeds
    //   coins_applied = max(coins_applied, baseline) so a game reboot (which
    //   zeroes coins_applied) does not re-apply coins the save already holds.
    // coins_applied: high-water mark, frame thread only (no atomic needed).
    // add_coin_fn: lazily resolved via hk::ro::lookupSymbol on first use.
    std::atomic<int> pending_coin_grant_total{0};
    std::atomic<int> pending_coin_baseline{0};
    int coins_applied = 0;
    void* add_coin_fn = nullptr;

    // ---- P3 ability tracking ------------------------------------------------
    //
    // Bridge ships an `ability_state` message — a full-overwrite snapshot of
    // per-ability received counts — on every HELLO replay and whenever a new
    // ability item arrives from AP. applyAbilityState() overwrites this table
    // and pops a Cappy bubble for any ability whose count rose above its
    // previously-stored value (newly unlocked, or a progressive chain that
    // leveled up).
    //
    // P3 TRACKS only: nothing reads ability_table to gate moves yet — that's
    // P4 enforcement. The duplicate-ability -> 100 coins conversion rides the
    // existing coin_grant path, not this table.
    //
    // Threading: the worker thread (ApClient::handleLine -> applyAbilityState)
    // is the sole writer. The unlock bubble is routed through
    // inbound_system_bubbles (NOT a direct CappyMessenger call) because
    // worker-thread CappyMessenger access crashes Ryujinx's ARMeilleure JIT —
    // same constraint enqueueSystemBubble works around. The seqlock
    // (even=stable, odd=writing) lets a future P4 frame-thread reader re-read
    // without a lock, matching the talkatoo_pools / shop_labels pattern.
    //
    // 32 slots x (64 name + 4 count) ~= 2 KiB BSS. Fixed buffers per the M6.1
    // allocator-safety contract.
    struct AbilitySlot {
        char name[kCheckFieldCap] = {};
        int count = 0;
    };
    static constexpr std::size_t kAbilityTableMax = kAbilityStateMax;
    AbilitySlot ability_table[kAbilityTableMax]{};
    std::size_t ability_table_count = 0;
    std::atomic<std::uint32_t> ability_table_seq{0};

    // Worker-thread write — full-overwrite the ability table from an
    // ability_state message. For every ability whose new count exceeds the
    // previously-stored count, enqueues a Cappy system bubble (via
    // inbound_system_bubbles) announcing the unlock / level-up. Idempotent: a
    // replayed snapshot with unchanged counts pops no bubbles.
    // `enforce` carries the abilitysanity flag: true (default) keeps the
    // gates active; false sets ability_gate_disabled so every gate reports
    // unlocked (abilitysanity off — the ability items aren't even in the pool).
    void applyAbilityState(const AbilityEntry* entries, std::size_t count,
                           bool enforce = true);

    // ---- P4 ability enforcement (frame-thread reads) ------------------------
    //
    // Frame-thread, lock-free count read over the seqlock-protected
    // ability_table written by applyAbilityState. Returns the received count
    // for `name` (e.g. how far a progressive chain has advanced), or 0 if the
    // ability is absent. Used by the judge-gate hooks (hooks/AbilityGateHook)
    // to decide whether a move is unlocked. Counts are monotonic (the bridge
    // only ever raises them), so a torn/stale read can only briefly UNDER-
    // report — never grant a move the player doesn't own.
    int abilityCount(const char* name) const;

    // True iff the player has received `name` to at least `level`
    // (abilityCount(name) >= level). Progressive chains map levels to moves:
    // e.g. abilityAtLeast("Progressive Crouch", 2) == "has Roll".
    bool abilityAtLeast(const char* name, int level) const;

    // Debug override: when true, every ability gate reports unlocked. Toggled
    // from the ImGui debug console (ApDebugConsole) so a mis-hooked judge can
    // never permanently brick a save during the P4 rollout. Frame-thread read,
    // console-thread write — atomic. Defaults FALSE (gates active) so the
    // enforcement is actually testable out of the box.
    std::atomic<bool> ability_gate_force_unlock{false};

    // abilitysanity OFF signal, set from the ability_state `enforce` field
    // (enforce=false -> disabled=true). Separate from the debug-console
    // force-unlock toggle so the two never clobber each other: abilityAtLeast
    // opens the gate when EITHER is set. Defaults FALSE (gates active) so a
    // seed that never sends ability_state still enforces. Worker-thread write
    // (applyAbilityState), frame-thread read — atomic.
    std::atomic<bool> ability_gate_disabled{false};

    // Local AP slot name — captured by ApClient when the bridge sends
    // hello_ack. Fixed buffer rather than std::string to avoid subsdk9's
    // libstdc++ allocator NULL-deref (see project_libstdcpp_allocator_broken_in_subsdk9.md).
    // Written once by the socket thread BEFORE conn.store(Ready) (release),
    // read by the frame thread AFTER conn == Ready (acquire) — the publish
    // ordering rides the existing conn-store fence.
    char local_slot[64] = {};

    // IUseSceneObjHolder* of HakoniwaSequence::curScene, refreshed every
    // frame by DrawMainHook and consumed by CappyMessenger::tryPump.
    //
    // Critical: this is NOT the raw StageScene* read from HakoniwaSequence
    // offset 0xB0. al::Scene has 4-way multiple inheritance
    // (NerveExecutor, IUseAudioKeeper, IUseCamera, IUseSceneObjHolder) and
    // the IUseSceneObjHolder sub-object lives at a non-zero offset. The
    // DrawMainHook does the static_cast<IUseSceneObjHolder*>(Scene*)
    // adjustment via the al::Scene header so the compile-time offset is
    // applied; the result of that cast is what gets stored here. Stored as
    // void* to keep this header free of game-side dependencies.
    std::atomic<void*> scene_cache{nullptr};

    // M6 phase B follow-up — pending capture grants awaiting GameDataHolder.
    //
    // When an AP capture ItemMsg drains in applyOnFrame BEFORE DrawMainHook
    // has cached game_data_holder_cache (boot, scene transition, fresh save
    // load), the in-line grantCapture call drops with "GameDataHolder not
    // cached yet" — captures_unlocked.set still runs (so the M7-A capture
    // lock lifts correctly), but the compendium-dict write is lost and the
    // Cappy message would fire without the unlock having visibly landed.
    //
    // Each failed grant pushes the Item here; the per-frame draw-hook tail
    // drains the queue after reconcileCaptureDictionary, retries grantCapture,
    // and fires the deferred Cappy message once the write succeeds. Item is
    // ~600 bytes of fixed char[] fields (no allocator path), so copying it
    // by value into the ring is M6.1-allocator-safe.
    //
    // Cap = 64 — sized to the full HELLO-replay capture burst (42 caps
    // today, with headroom for future apworld additions). The earlier cap
    // of 16 matched applyOnFrame's per-frame drain limit, but in practice
    // the GDH-down window after a reconnect lasts many frames — so the
    // 16-cap and 26-cap follow-up drains all pile into the ring before the
    // reconciler can fire its first retry. Pre-fix symptom: captures past
    // slot 16 in a HELLO replay against an un-loaded save got dropped with
    // "pending_capture_grant FULL" warns and never landed in SMO's dict.
    // The ring is frame-thread-only on both ends; SpscRing just gives us
    // the same shape as the other queues.
    SpscRing<Item, 64> pending_capture_grant;

    // Apply queued inbound items to the game (frame thread).
    void applyOnFrame();

    // Per-frame post-applyOnFrame tail: drains pending_capture_grant. Called
    // from DrawMainHook right after reconcileCaptureDictionary so any dict
    // writes the reconciler just landed are visible to the queue's
    // grantCapture retry. Items whose grant still fails stay queued for the
    // next frame; items whose grant succeeds emit their deferred Cappy
    // message and pop. Frame-thread only.
    void flushPendingCaptureGrants();
    // P1: apply pending Cap coin grant to GameDataFunction::addCoin.
    void applyCoinGrant();

    // Hash a Check message body for dedupe purposes.
    static std::uint64_t hashCheck(const Check&);

    // Monotonic milliseconds. Backed by nn::os::GetSystemTick; safe to call
    // from either thread.
    static std::int64_t nowMs();

private:
    ApState() {
        // Fill the palette table with the "no override" sentinel so a shine
        // we've never scouted just runs orig() and keeps its stage default.
        for (auto& slot : shine_palette) slot = kNoPaletteOverride;
        // kingdom_gate[] defaults to -1 ("vanilla") — array NSDMI can't
        // express a non-zero fill, so it happens here.
        resetKingdomGates();
        // chain_origin_bit[] defaults to 0xff ("unknown origin") — same
        // array-NSDMI limitation as kingdom_gate[].
        for (auto& b : chain_origin_bit)
            b.store(0xff, std::memory_order_relaxed);
    }

    // Drain inbound_kill_pending; called from applyOnFrame.
    void maybeApplyInboundKill();
};

}  // namespace smoap::ap
