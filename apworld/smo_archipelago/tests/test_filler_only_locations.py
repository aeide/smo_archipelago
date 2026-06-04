"""Filler-only location audit: locations.json `filler_only: true` flags vs the
authoritative list of permanently-missable locations on SMO 1.0.0.

Why this exists. On SMO 1.0.0 (our target version), two documented sequence
breaks can leave a Cascade Kingdom Power Moon permanently unobtainable:

  - Broode Skip (https://smo.wiki/Broode_Skip) — collect 5 Cascade Power Moons
    via the 2P warp-painting trick, leave Cascade without fighting Madame
    Broode. The "Multi Moon Atop the Falls" never spawns and never re-spawns
    on 1.0.0 (1.0.1+ auto-awards on return; we target 1.0.0).
  - First Moon Skip (https://smo.wiki/First_Moon_Skip) — on 1.0.0 the Madame
    Broode loading zone is active before the first moon spawns. If the player
    triggers the fight without first collecting "Our First Power Moon", the
    cutscene reference becomes invalid, the game crashes on a later attempt,
    and the moon never registers in the save.

If AP placed a progression item at either location, a player who hit either
skip would be permanently soft-locked with no recovery path. The hook in
hooks/World.py::_apply_filler_only_rules forbids progression items from
landing at any location marked `filler_only: true` in locations.json.

Every other kingdom — per Mario Wiki Missable_content and the 1.0.0 / 1.0.1
patch notes — has NO permanently-missable moons in normal play or via
documented 1.0.0 sequence breaks. The Cookatiel-fight / Big-Pot pair in
Luncheon shares scenario_no 2->3 (only one collection advances the scenario),
but both moons stay physically collectible in either order, so neither is
missable. If a new missable case is discovered, add the location to
EXPECTED_FILLER_ONLY here AND tag it in locations.json.

Pure-data: no Archipelago imports, no Switch dependency. Runs in the standard
test job (not gated on SMOAP_LIVE_AP).
"""

from __future__ import annotations

import json
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


EXPECTED_FILLER_ONLY = frozenset({
    "Cascade: Our First Power Moon",
    "Cascade: Multi Moon Atop the Falls",
})


def _load_locations() -> list[dict]:
    return json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8")
    )


def _flagged_names(locs: list[dict]) -> set[str]:
    return {loc["name"] for loc in locs if loc.get("filler_only", False)}


def test_filler_only_set_matches_audit():
    """The flagged set is exactly the audited list."""
    flagged = _flagged_names(_load_locations())
    extra = flagged - EXPECTED_FILLER_ONLY
    missing = EXPECTED_FILLER_ONLY - flagged
    assert flagged == EXPECTED_FILLER_ONLY, (
        f"locations.json filler_only flags drift from the audit:\n"
        f"  In locations.json but not audited: {sorted(extra)}\n"
        f"  Audited but missing from locations.json: {sorted(missing)}\n"
        f"If this drift is intentional, update EXPECTED_FILLER_ONLY here "
        f"AND record the missability rationale in this docstring."
    )


def test_filler_only_flag_is_boolean_true():
    """The flag is `true` (not 1, not a string, not present-but-false)."""
    locs = _load_locations()
    for loc in locs:
        if "filler_only" not in loc:
            continue
        v = loc["filler_only"]
        assert v is True, (
            f"{loc['name']}: filler_only must be boolean true (got {v!r}); "
            f"either set it to true or remove the key."
        )


def test_filler_only_locations_exist_in_table():
    """Every audited name actually exists in locations.json (typo guard)."""
    locs = _load_locations()
    all_names = {loc["name"] for loc in locs}
    missing = EXPECTED_FILLER_ONLY - all_names
    assert not missing, (
        f"EXPECTED_FILLER_ONLY references names not present in locations.json: "
        f"{sorted(missing)}"
    )
