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

}  // namespace smoap::game
