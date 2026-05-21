"""Consistency check: locations.json `progression: true` flags vs the
authoritative scenario-advance list for Talkatoo% mode.

Phase 4's Talkatoo% block (switch-mod/src/hooks/MoonGetHook.cpp) refuses
moon collection unless Talkatoo has named the moon — except for moons
marked `progression: true` in this apworld's locations.json, which are
always collectible. Those exemptions prevent fresh-start soft-locks on
moons that advance SMO's internal `scenario_no` (Multi Moons, boss-fight
clears, and explicit prereqs like Seaside's 4 seals).

The data we test here:

  - Every `progression: true` name actually exists in locations.json
    (typo guard). A dangling flag would silently fail because the bridge
    + sync_shine_table.py both filter on name equality.
  - The set matches the audited list. The audit was anchored on
    mariowiki.com/Multi_Moon's per-kingdom Multi Moon entries plus the
    explicit per-kingdom prereqs (Seaside seals, Bowser's 4-step chain,
    Cascade's first power moon). See the inline EXPECTED_PROGRESSION
    comment for the source-of-truth break-down.

Pure-data: no Archipelago imports, no Switch dependency. Runs in the
standard test job (not gated on SMOAP_LIVE_AP).

When this fails:
  - "missing name" → typo or a moon was renamed. Either fix the name or
    drop the flag.
  - "set differs" → someone changed the progression list. If the change
    is deliberate, update EXPECTED_PROGRESSION here AND update the audit
    rationale in docs/milestones.md (Phase 4 narrative).
"""

from __future__ import annotations

import json
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


# Audited 2026-05-21 against mariowiki.com/Multi_Moon + per-kingdom
# story walkthroughs. Source-of-truth for the per-kingdom rationale:
#   - Cascade: 2-scenario kingdom. "Our First Power Moon" gates story 1->2;
#              "Multi Moon Atop the Falls" (Madame Broode) caps story 2.
#   - Sand: 2 Multi Moons — Hariet ("Showdown on the Inverted Pyramid"),
#           Knucklotec ("The Hole in the Desert").
#   - Lake: "Broodals Over the Lake" (Rango MM).
#   - Wooded: 2 Multi Moons — Spewart ("Flower Thieves of Sky Garden",
#             story 1->2), Torkdrift ("Defend the Secret Flower Field!",
#             story 2->3).
#   - Metro: 2 Multi Moons — Mechawiggler ("New Donk City's Pest Problem"),
#            Pauline ("A Traditional Festival!").
#   - Snow: "The Bound Bowl Grand Prix".
#   - Seaside: 4 seal prereqs + Mollusque MM. Seals spawn Mollusque;
#              Mollusque drops the Multi Moon ("The Glass Is Half Full!").
#   - Luncheon: 2 Multi Moons — Cookatiel-meat ("Big Pot on the Volcano:
#               Dive In!"), Cookatiel-fight ("Cookatiel Showdown!").
#   - Ruined: "Battle with the Lord of Lightning!" (Ruined Dragon MM).
#   - Bowser's: 4-step story chain — Infiltrate -> Smart Bombing ->
#               Big Broodal Battle -> Showdown (RoboBrood MM). All four
#               required for the chain to complete; only the last is a
#               Multi Moon, the others are single-moon story missions
#               that advance scenario_no.
# Intentionally NOT included (per audit):
#   - Cap, Lost, Cloud, Mushroom, Moon, Dark Side, Darker Side. Cap has no
#     in-kingdom progression gate; Lost has no Multi Moon at all per
#     Mario Wiki; Cloud / Mushroom / Moon are one-moon transitional /
#     post-game kingdoms; Dark / Darker Side are post-credits and AP-pool
#     exclusion is handled separately.
EXPECTED_PROGRESSION = frozenset({
    "Cascade: Our First Power Moon",
    "Cascade: Multi Moon Atop the Falls",
    "Sand: Showdown on the Inverted Pyramid",
    "Sand: The Hole in the Desert",
    "Lake: Broodals Over the Lake",
    "Wooded: Flower Thieves of Sky Garden",
    "Wooded: Defend the Secret Flower Field!",
    "Metro: New Donk City's Pest Problem",
    "Metro: A Traditional Festival!",
    "Snow: The Bound Bowl Grand Prix",
    "Seaside: The Stone Pillar Seal",
    "Seaside: The Lighthouse Seal",
    "Seaside: The Hot Spring Seal",
    "Seaside: The Seal Above the Canyon",
    "Seaside: The Glass Is Half Full!",
    "Luncheon: Big Pot on the Volcano: Dive In!",
    "Luncheon: Cookatiel Showdown!",
    "Ruined: Battle with the Lord of Lightning!",
    "Bowser's: Infiltrate Bowser's Castle!",
    "Bowser's: Smart Bombing",
    "Bowser's: Big Broodal Battle",
    "Bowser's: Showdown at Bowser's Castle",
})


def _load_locations() -> list[dict]:
    return json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8")
    )


def _flagged_names(locs: list[dict]) -> set[str]:
    return {loc["name"] for loc in locs if loc.get("progression", False)}


def test_every_flagged_name_exists():
    """Every name marked `progression: true` is itself a valid loc name."""
    locs = _load_locations()
    all_names = {loc["name"] for loc in locs}
    flagged = _flagged_names(locs)
    # The flagged set is a subset of names by construction (we only flag
    # entries we iterate over), but assert it explicitly so a future
    # refactor that builds the flags from elsewhere doesn't silently break.
    missing = flagged - all_names
    assert not missing, (
        f"locations.json has progression-flagged names not present in the "
        f"name set: {sorted(missing)}"
    )


def test_progression_set_matches_audit():
    """The flagged set is exactly the audited list."""
    flagged = _flagged_names(_load_locations())
    extra = flagged - EXPECTED_PROGRESSION
    missing = EXPECTED_PROGRESSION - flagged
    assert flagged == EXPECTED_PROGRESSION, (
        f"locations.json progression flags drift from the audit:\n"
        f"  In locations.json but not audited: {sorted(extra)}\n"
        f"  Audited but missing from locations.json: {sorted(missing)}\n"
        f"If this drift is intentional, update EXPECTED_PROGRESSION here "
        f"AND record the audit rationale in docs/milestones.md."
    )


def test_progression_count_matches_audit():
    """Cardinality check — fast signal if anything moved."""
    flagged = _flagged_names(_load_locations())
    assert len(flagged) == len(EXPECTED_PROGRESSION), (
        f"progression count drift: got {len(flagged)}, expected "
        f"{len(EXPECTED_PROGRESSION)}"
    )


def test_no_capture_marked_progression():
    """Captures don't fit the scenario-advance pattern.

    Captures are AP items applied to SMO's HackDictionary; they don't go
    through MoonGetHook so flagging them as progression has no in-game
    effect. Marking one is a typing error.

    (NOTE: victory locations CAN legitimately be progression-flagged.
    Metro: A Traditional Festival! is the festival% goal AND a Multi Moon
    that advances Metro's scenario_no — both flags apply. The goal flag
    is consumed by CreditsStartHook / festival-mode logic; the progression
    flag is consumed by MoonGetHook's Talkatoo% block. Different concerns,
    no conflict.)
    """
    locs = _load_locations()
    for loc in locs:
        if not loc.get("progression", False):
            continue
        assert "Capture" not in loc.get("category", []), (
            f"{loc['name']} is a Capture but flagged progression; remove flag"
        )


def test_progression_moons_have_kingdom_prefix():
    """Every progression entry follows the `Kingdom: Moon Name` form.

    The bridge-side filter (Phase 4 follow-up #1) plans to use the prefix
    to route progression moons to the right per-kingdom talkatoo_pool
    exclusion list. Defensively check the schema is honored.
    """
    bad = []
    for name in EXPECTED_PROGRESSION:
        if ":" not in name:
            bad.append(name)
            continue
        kingdom = name.split(":", 1)[0].strip()
        if not kingdom or kingdom == name:
            bad.append(name)
    assert not bad, (
        f"progression entries missing 'Kingdom: ' prefix: {bad}"
    )
