// M7 Path A — fork-cinematic kingdom-order gate.
//
// At SMO's two world-map bifurcations the player should be funneled into the
// linear-prior kingdom on the fork cinematic UNTIL they've actually been
// there at least once:
//   - Post-Sand: Wooded substituted to Lake (until Mario visits Lake)
//   - Post-Metro: Seaside substituted to Snow (until Mario visits Snow)
//
// Why a release condition: `calcNextLockedWorldIdForWorldMap` (the hook
// installed for the cinematic) ALSO fires on the regular world map that
// opens when Mario boards the Odyssey to leave a kingdom. So an
// unconditional substitution would trap Mario in a Lake loop — every time
// he tries to leave Lake the regular map would re-substitute Wooded->Lake
// and send him right back. The release condition narrows the substitution
// to "Mario hasn't been to Lake yet," which is what the cinematic
// presentation is supposed to enforce.
//
// "Visited" is a sticky bit in ApState::visited_kingdoms, OR'd each frame
// from `getCurrentWorldIdNoDevelop` (same plumbing AddPayShineHook uses to
// resolve the current kingdom for deposit accounting). Session-only — see
// the comment on ApState::visited_kingdoms for the save-reload behavior.
//
// History: the earlier threshold design (e505c5c, "gate Wooded/Seaside on
// lifetime AP-receipts") soft-locked when lifetime receipts climbed past N
// from other players' completions of own-slot moons before Mario had ever
// visited the prereq. The visited-bit signal is the correct one: it answers
// "has Mario actually played in this kingdom?" rather than "has AP given
// him enough items to satisfy the leave-threshold?"

#pragma once

#include <cstdint>

namespace smoap::game {

struct OrderGateDecision {
    // True if the player's choice should be substituted with the prereq
    // kingdom. When true, required_kingdom_short and required_stage point
    // to the prereq the cinematic should fly to. When false the remaining
    // fields are nullptr.
    bool blocked = false;

    // Apworld kingdom short name ("Lake", "Snow"). nullptr when !blocked.
    const char* required_kingdom_short = nullptr;

    // SMO HomeStage name ("LakeWorldHomeStage", "SnowWorldHomeStage"). nullptr
    // when !blocked. Suitable for passing to GameDataFunction::
    // tryChangeNextStageWithDemoWorldWarp.
    const char* required_stage = nullptr;
};

// Evaluate the gate for a kingdom the player just picked, identified by
// apworld short name ("Wooded", "Seaside", etc.). Returns blocked=true for
// gated kingdoms whose prereq Mario hasn't visited yet; blocked=false for
// non-gated kingdoms (Cap, Cascade, Lake, Snow, Luncheon, ...) and for
// gated kingdoms whose prereq has been visited.
OrderGateDecision evaluateOrderGateForKingdom(const char* kingdom_short);

// --- Free-detour "both siblings before the exit" gate ------------------------
//
// SMO has two world-map detour pairs, both made FREE (the kRules order entries
// are gone) — the player may fly the two siblings in either order:
//   - Post-Sand:  Lake ↔ Wooded, exit into Cloud
//                 (story-forced: select Metro on the map → Bowser cutscene →
//                  Cloud pre-peace)
//   - Post-Metro: Snow ↔ Seaside, exit into Luncheon (a normal onward flight —
//                 no Bowser intercept; the exit stage resolves to Luncheon
//                 directly)
// Leaving a detour into its exit kingdom must require the minimum effective-moon
// counts from BOTH siblings. The exit kingdom is the chokepoint, caught at the
// universal GameDataFile::changeNextStage commit where the destination provably
// resolves. See docs/v3-feasibility/future-feasibility-lake-wooded-free-detour.md.

struct DetourExitGateDecision {
    // True when the player has NOT yet met both siblings' leave-thresholds, i.e.
    // the warp into the exit kingdom should be held back into the detour. When
    // true, redirect_stage is the unmet sibling's HomeStage. When false the
    // player may proceed (pass-through). exit_kingdom is non-null only when
    // exit_kingdom_short names a known detour exit (doubles as the "is this a
    // detour exit?" test); the *_short / have / need fields are populated for
    // diagnostics/logging whenever exit_kingdom is set.
    bool blocked = false;
    const char* redirect_stage = nullptr;  // unmet sibling HomeStage
    const char* exit_kingdom = nullptr;     // "Cloud" / "Luncheon" (null = N/A)
    const char* a_short = nullptr;          // first sibling  ("Lake" / "Snow")
    const char* b_short = nullptr;          // second sibling ("Wooded" / "Seaside")
    int a_have = 0, a_need = 0;
    int b_have = 0, b_need = 0;
};

// Evaluate the "both siblings' thresholds met" gate guarding the warp into a
// detour exit kingdom (exit_kingdom_short = "Cloud" or "Luncheon"). Reads each
// sibling's lifetime effective-moon credit (outstanding + deposited) against the
// rolled-gate-aware leave-thresholds (ApState::kingdom_gate[bit], -1 ⇒ vanilla:
// Lake=8/Wooded=16, Snow=10/Seaside=10). Returns exit_kingdom=nullptr (fail open)
// when exit_kingdom_short is not a detour exit or the kingdom table can't resolve
// the siblings.
DetourExitGateDecision evaluateDetourExitGate(const char* exit_kingdom_short);

// Per-kingdom DEPOSITED effective-moon count (the save's PayShineNum for the
// kingdom, via the M6 PaySnapshot symbol plumbing). 0 when the symbol/holder
// isn't ready. This is the same "have I paid the Odyssey" read the launch
// check consumes — exported for UnlockShineNumHook's chain-return takeoff
// allowance ("open the gate while chain-reached AND the rolled leave-gate is
// unpaid").
int depositedEffectiveMoons(std::uint8_t bit);

// True when the player has collected AT LEAST this kingdom's rolled leave-gate
// in lifetime effective moons (outstanding + deposited) — i.e. "enough moons to
// leave and progress the story." Used by WorldMapSelectHook's chain-return
// bounce so that a chain-reached kingdom whose leave-gate is MET no longer
// bounces forward flights (Devon 2026-07-15: enough moons -> progress, no matter
// the scenario; this intentionally reverses the P5 finding-13 "paying never
// legitimizes story-forward travel" ruling). Conservative when the rolled gate
// is unknown (kingdom_gate[bit] == -1, i.e. randomize_kingdom_gates off): returns
// false so the pre-existing bounce behavior is preserved for those seeds.
bool leaveGateSatisfied(std::uint8_t bit);

}  // namespace smoap::game
