// Hook on GameDataFunction::addPayShine(GameDataHolderWriter, s32) and the
// "pay everything" sibling addPayShineCurrentAll(GameDataHolderWriter).
//
// This is THE chokepoint for moon "spend" in SMO. When Mario hand-tosses a
// moon at an Odyssey, vanilla does NOT decrement mShineNum directly — it calls
// GameDataFile::addPayShine which monotonically grows a separate PayShineNum
// counter (capped at findUnlockShineNum[K] = moons-required-to-leave). The
// HUD's spendable-fuel total is `getCurrentShineNum() = ShineNum - PayShineNum`
// clamped to 0.
//
// We hook the public GameDataFunction wrappers (not the GameDataFile members,
// which are inlined into all callers in 1.0.0 main.nso). After Orig runs,
// we snapshot the new per-kingdom PayShineNum via ApState::buildPaySnapshot
// and push the snapshot into pending_pay_snapshots. The worker picks it up
// in pumpOnce and ships it as PaySnapshotMsg. The bridge derives
// outstanding = lifetime_received_AP − PayShineNum.
//
// On bridge offline: SUPPRESS Orig — ShineNumGetHook returns 0 when offline
// so the Odyssey UI refuses fuel, but be defensive in case a scripted path
// still reaches us.
//
// IMPORTANT: no local ap_moons_kingdom[bit] debit anymore. The bridge is the
// only source of truth for that counter; it ships OutstandingMsg right after
// receiving the snapshot, which the Switch overwrites into
// ap_moons_kingdom. Eliminates the deposit-then-crash data-loss class — see
// plan `make-a-plan-first-reactive-elephant.md`.

#include "lib.hpp"

#include "AddPayShineHook.hpp"

#include "../ap/ApClient.hpp"
#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

#include <cstring>

// Minimal layout mirror. GameDataHolderWriter is a 1-pointer trivially-
// copyable wrapper (Itanium ABI passes in x0). Same shape as the one used
// by CaptureGate / addHackDictionary call sites.
struct GameDataHolderWriter   { void* mData; };
struct GameDataHolderAccessor { void* mData; };

namespace smoap::hooks {

namespace {

using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);

// Resolve the current kingdom from cached game data holder. Returns 0xff
// on any failure (no cached holder / unresolved fn / out-of-range world id).
// Caller treats 0xff as "kingdom unknown — log only; snapshot still fires
// since other kingdoms' PayShineNum is unaffected".
int resolveCurrentKingdomBit() {
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(s.get_current_world_id_fn);
    GameDataHolderAccessor acc{holder};
    const int world_id = fn(acc);
    return smoap::game::kingdomBitForWorldId(world_id);
}

// Build the snapshot from the live GameDataHolder and queue it for the
// worker. Last-snapshot-wins coalescing in the ring is desirable — every
// snapshot is a complete reading. Shared by both hooks below.
void queuePaySnapshot(const char* tag) {
    auto& s = smoap::ap::ApState::instance();
    smoap::ap::ApState::PendingPaySnapshot ps{};
    if (!s.buildPaySnapshot(ps)) {
        SMOAP_LOG_WARN("[%s] snapshot build FAILED (gdh=%p, fn=%p) — "
                       "bridge won't see this deposit until next snapshot",
                       tag,
                       s.game_data_holder_cache.load(std::memory_order_relaxed),
                       s.get_pay_shine_num_fn);
        return;
    }
    if (!s.pending_pay_snapshots.push(ps)) {
        // Ring full (4 slots): the worker hasn't drained as fast as
        // deposits are arriving. Since every snapshot is complete, the
        // older queued entries are redundant — but we don't have a
        // pop-and-overwrite API. Log and accept: the next snapshot the
        // worker drains gives the bridge an authoritative reading
        // anyway. In practice 4 slots is plenty (Odyssey fuel-up
        // animation gates deposits to ~once per few seconds).
        SMOAP_LOG_WARN("[%s] pending_pay_snapshots ring full — dropping "
                       "(bridge will catch up on next snapshot)", tag);
    }
}

HOOK_DEFINE_TRAMPOLINE(AddPayShineHook) {
    static void Callback(GameDataHolderWriter writer, int count) {
        auto& s = smoap::ap::ApState::instance();

        // Defensive: when bridge is offline, ShineNumGetHook returns 0 so
        // the Odyssey UI should refuse fuel before this hook is ever
        // reached. If somehow we fire anyway (scripted scenario, future
        // code path), SKIP Orig too so vanilla PayShine doesn't move out
        // of sync with our (zeroed) HUD.
        if (!s.bridge_connected.load(std::memory_order_relaxed)) {
            SMOAP_LOG_WARN("[m6-deposit] addPayShine count=%d BLOCKED (bridge offline)",
                           count);
            return;
        }

        // Resolve kingdom BEFORE Orig for logging only — we no longer
        // care from a correctness standpoint since the snapshot reads
        // PayShineNum for ALL kingdoms after Orig.
        const std::uint8_t bit = static_cast<std::uint8_t>(resolveCurrentKingdomBit());

        Orig(writer, count);  // vanilla bumps PayShineNum

        SMOAP_LOG_INFO("[m6-deposit] addPayShine count=%d kingdom=%s(bit=%u); "
                       "queuing PaySnapshot for bridge",
                       count,
                       bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>",
                       bit);

        queuePaySnapshot("m6-deposit");
    }
};

// addPayShineCurrentAll — "pay everything in current kingdom" (probably
// used by kingdom-complete celebrations). Same snapshot treatment: Orig
// runs, then we sample PayShineNum.
HOOK_DEFINE_TRAMPOLINE(AddPayShineAllHook) {
    static void Callback(GameDataHolderWriter writer) {
        auto& s = smoap::ap::ApState::instance();

        if (!s.bridge_connected.load(std::memory_order_relaxed)) {
            SMOAP_LOG_WARN("[m6-deposit] addPayShineCurrentAll BLOCKED (bridge offline)");
            return;
        }

        const std::uint8_t bit = static_cast<std::uint8_t>(resolveCurrentKingdomBit());

        Orig(writer);

        SMOAP_LOG_INFO("[m6-deposit-all] addPayShineCurrentAll kingdom=%s(bit=%u); "
                       "queuing PaySnapshot for bridge",
                       bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>",
                       bit);

        queuePaySnapshot("m6-deposit-all");
    }
};

}  // namespace

void installAddPayShineHook() {
    SMOAP_LOG_INFO("installing AddPayShineHook -> %s",
                   smoap::sym::kGameDataFunctionAddPayShine);
    softInstallAtSymbol<AddPayShineHook>(smoap::sym::kGameDataFunctionAddPayShine);
}

void installAddPayShineAllHook() {
    SMOAP_LOG_INFO("installing AddPayShineAllHook -> %s",
                   smoap::sym::kGameDataFunctionAddPayShineCurrentAll);
    softInstallAtSymbol<AddPayShineAllHook>(smoap::sym::kGameDataFunctionAddPayShineCurrentAll);
}

}  // namespace smoap::hooks
