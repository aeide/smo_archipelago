#include "KingdomOrderGate.hpp"

#include <cstring>

#include "../ap/ApState.hpp"
#include "KingdomUnlock.hpp"

namespace smoap::game {

namespace {

struct Rule {
    const char* picked;          // kingdom short name the player picked
    const char* prereq;          // kingdom short name to redirect to
    const char* prereq_stage;    // SMO HomeStage for the redirect
};

// Strict fork-order substitution table. BOTH historical entries are gone:
// Lake/Wooded AND Snow/Seaside are now "free detours" — after the bifurcation
// the player may fly either sibling first, with the apworld logic + the in-game
// evaluateDetourExitGate requiring the minimum moon counts from BOTH siblings
// before the onward exit transition (Lost/Cloud and Luncheon respectively). See
// docs/v3-feasibility/future-feasibility-lake-wooded-free-detour.md.
//
// The table is retained (with an inert sentinel) as the seam for any FUTURE
// strict-order fork — a real entry would name the picked kingdom, its prereq,
// and the prereq's canonical SMO 1.0.0 HomeStage (matching KINGDOM_FOR_HOMESTAGE
// in scripts/extract_shine_map.py). evaluateOrderGateForKingdom skips the
// sentinel, so with no active rules it's a no-op.
constexpr Rule kRules[] = {
    {nullptr, nullptr, nullptr},  // sentinel — no active fork order-rules
};

// Resolve Mario's currently-occupied kingdom bit on demand from the cached
// GameDataHolder + getCurrentWorldIdNoDevelop symbol (same plumbing
// AddPayShineHook uses for deposit accounting). Returns 0xff when the holder
// or symbol isn't ready (caller treats as "not current").
std::uint8_t currentKingdomBit() {
    struct GameDataHolderAccessor { void* mData; };
    using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(s.get_current_world_id_fn);
    GameDataHolderAccessor acc{holder};
    return kingdomBitForWorldId(fn(acc));
}

}  // namespace

OrderGateDecision evaluateOrderGateForKingdom(const char* kingdom_short) {
    OrderGateDecision d{};
    if (!kingdom_short || !*kingdom_short) return d;

    for (const auto& r : kRules) {
        if (!r.picked) continue;  // sentinel / disabled rule
        if (std::strcmp(kingdom_short, r.picked) != 0) continue;

        // Release condition: the prereq kingdom must be either
        //   (a) sticky-visited in this session (Mario flew there via a
        //       cinematic or regular-map commit — see ApState::visited_kingdoms
        //       and the TryChange* hooks in WorldMapSelectHook), or
        //   (b) Mario's currently-occupied kingdom (handles the save-reload-
        //       into-prereq case where visited bits would otherwise be cold).
        // (b) is a same-frame query of getCurrentWorldIdNoDevelop, distinct
        // from the per-frame poll the earlier design used: this fires only
        // when the gate is consulted (calcNextLocked / tryChange), not every
        // tick, so a save-reload doesn't pollute visited_kingdoms.
        //
        // Unknown prereq → fail open (better than soft-lock).
        const std::uint8_t prereq_bit = kingdomBitFor(r.prereq);
        if (prereq_bit >= 17) return d;

        auto& st = smoap::ap::ApState::instance();
        if (st.isKingdomBitVisited(static_cast<int>(prereq_bit))) {
            return d;  // (a) visited — released
        }
        if (currentKingdomBit() == prereq_bit) {
            return d;  // (b) currently in prereq — released
        }

        d.blocked                = true;
        d.required_kingdom_short = r.prereq;
        d.required_stage         = r.prereq_stage;
        return d;
    }
    return d;  // not a gated kingdom
}

namespace {

// The two free-detour pairs. exit_short is the kingdom the player leaves the
// detour into; {a,b}_short are the two siblings (a is the redirect priority when
// both are unmet); {a,b}_stage are their canonical SMO 1.0.0 HomeStages;
// {a,b}_vanilla are the Odyssey leave-thresholds (effective moons) used when no
// rolled gate is present (kingdom_gate[bit] == -1).
struct DetourPair {
    const char* exit_short;
    const char* a_short;  const char* a_stage;  int a_vanilla;
    const char* b_short;  const char* b_stage;  int b_vanilla;
};
constexpr DetourPair kDetourPairs[] = {
    {"Cloud",
     "Lake", "LakeWorldHomeStage",   8,
     "Wooded", "ForestWorldHomeStage", 16},
    {"Luncheon",
     "Snow", "SnowWorldHomeStage",   10,
     "Seaside", "SeaWorldHomeStage",  10},
};

// Per-kingdom DEPOSITED effective-moon count, read live from the save via the
// by-world getPayShineNum the M6 PaySnapshot path already resolves
// (ApState::get_pay_shine_num_fn). Reading game state means it survives save
// reloads, unlike any Switch-side accumulator. Returns 0 when the symbol/holder
// isn't ready yet.
int depositedEffectiveMoons(std::uint8_t bit) {
    if (bit >= 17) return 0;
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_pay_shine_num_fn) return 0;
    const char* name = smoap::game::kingdomForBit(bit);
    if (!name || !*name) return 0;
    const int world_id = smoap::game::worldIdFromKingdomShort(name);
    if (world_id < 0) return 0;
    struct GameDataHolderAccessor { void* mData; };
    auto fn = reinterpret_cast<int (*)(GameDataHolderAccessor, int)>(
        s.get_pay_shine_num_fn);
    const int n = fn(GameDataHolderAccessor{holder}, world_id);
    return n < 0 ? 0 : n;
}

// Per-kingdom LIFETIME-received effective moons (Multi-Moon=3, Power-Moon=1).
// = outstanding (ApState::ap_moons_kingdom — the SPENDABLE balance that drops to
// 0 once the player fuels the Odyssey) + deposited (above). The bridge defines
// outstanding = lifetime_received − PayShineNum, so the sum reconstructs
// lifetime_received and is NOT depleted by depositing. That depletion was the
// bug that blocked this gate even with both thresholds collected, after the
// player paid the Odyssey (playtest 2026-06-25). This mirrors KingdomMoons() in
// the apworld logic, which counts RECEIVED moons regardless of deposit. (A just-
// deposited frame may transiently over-count if the bridge's new outstanding
// hasn't arrived yet — harmless for a >= gate, never falsely blocks.)
int collectedEffectiveMoons(std::uint8_t bit) {
    if (bit >= 17) return 0;
    const int outstanding = smoap::ap::ApState::instance()
        .ap_moons_kingdom[bit].load(std::memory_order_relaxed);
    return outstanding + depositedEffectiveMoons(bit);
}

// Rolled leave-threshold for a kingdom, falling back to its vanilla value when
// randomize_kingdom_gates is off (kingdom_gate[bit] == -1).
int leaveThreshold(std::uint8_t bit, int vanilla) {
    if (bit >= 17) return vanilla;
    const int rolled = smoap::ap::ApState::instance()
        .kingdom_gate[bit].load(std::memory_order_relaxed);
    return rolled >= 0 ? rolled : vanilla;
}

}  // namespace

DetourExitGateDecision evaluateDetourExitGate(const char* exit_kingdom_short) {
    DetourExitGateDecision d{};
    if (!exit_kingdom_short || !*exit_kingdom_short) return d;

    const DetourPair* pair = nullptr;
    for (const auto& p : kDetourPairs) {
        if (std::strcmp(exit_kingdom_short, p.exit_short) == 0) { pair = &p; break; }
    }
    if (!pair) return d;  // not a detour exit → fail open (exit_kingdom stays null)

    const std::uint8_t a = kingdomBitFor(pair->a_short);
    const std::uint8_t b = kingdomBitFor(pair->b_short);
    if (a >= 17 || b >= 17) return d;  // fail open (table mis-config)

    d.exit_kingdom = pair->exit_short;
    d.a_short = pair->a_short;
    d.b_short = pair->b_short;
    d.a_have  = collectedEffectiveMoons(a);
    d.a_need  = leaveThreshold(a, pair->a_vanilla);
    d.b_have  = collectedEffectiveMoons(b);
    d.b_need  = leaveThreshold(b, pair->b_vanilla);

    const bool a_ok = d.a_have >= d.a_need;
    const bool b_ok = d.b_have >= d.b_need;
    if (a_ok && b_ok) return d;  // both met → proceed to the exit kingdom

    // Hold the player in the detour: send them to whichever sibling is unmet
    // (a first if both are unmet). Matches the M7 Path A BACKSTOP redirect
    // mechanism — substituting the commit stage rewrites the destination.
    d.blocked        = true;
    d.redirect_stage = !a_ok ? pair->a_stage : pair->b_stage;
    return d;
}

}  // namespace smoap::game
