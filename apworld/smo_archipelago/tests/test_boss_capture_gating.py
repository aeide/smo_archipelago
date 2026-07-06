"""Invariant: every boss kingdom's PEACE-ANCHOR moon requires the captures needed
to defeat that kingdom's boss.

Each hooks/Rules.py `<Kingdom>Peace()` resolves (via canReachLocation) to the
story-completing "anchor" moon below. Every post-peace moon — moon-rock and
non-rock — gates on `{<Kingdom>Peace()}`, and every entrance-shuffle moon-pipe DOOR
gates on the same Peace function (entrance_logic.MOON_PIPE_PEACE_FUNCS). So requiring
the boss captures on the anchor makes ALL of that content transitively require them,
with no per-moon / per-door edit. This test locks that wiring: if a future
moon_requirements / compile_moon_logic edit drops a boss capture from an anchor (CSV
drift, or a new boss kingdom left unwired), generation could strand that capture behind
the very post-peace layer it unlocks — the Cap-Paragoomba / Sand-Knucklotec self-lock
class. See scripts/compile_moon_logic.py::BOSS_CAPTURE_GATES.

Cascade is intentionally absent: its boss capture (Broode's Chain Chomp) is a FIXED
STARTER (hooks/World.py FIXED_STARTER_CAPTURES), always precollected, so it never needs
to appear in the anchor's requires.
"""

from __future__ import annotations

import json
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]

# anchor moon (== the location <Kingdom>Peace() reaches for) -> boss captures that
# MUST appear (as |item| tokens) in its compiled requires. Bullet Bill is split off
# onto Sand's Showdown fight (reachable pre-Fist) to keep the capturesanity chain
# acyclic; The Hole in the Desert (the SandPeace anchor) then needs both.
EXPECTED_BOSS_CAPTURES: dict[str, list[str]] = {
    "Sand: Showdown on the Inverted Pyramid":      ["Bullet Bill"],
    "Sand: The Hole in the Desert":                ["Bullet Bill", "Knucklotec's Fist"],
    "Lake: Broodals Over the Lake":                ["Zipper"],
    "Wooded: Defend the Secret Flower Field!":     ["Uproot"],
    "Metro: A Traditional Festival!":              ["Spark pylon"],
    "Snow: The Bound Bowl Grand Prix":             ["Shiverian Racer"],
    "Seaside: The Glass Is Half Full!":            ["Gushen"],
    "Luncheon: Cookatiel Showdown!":               ["Volbonan", "Lava Bubble"],
    "Bowser's: Showdown at Bowser's Castle":       ["Pokio", "Spark pylon"],
    "Ruined: Battle with the Lord of Lightning!":  ["Spark pylon"],
}


def _requires_by_name() -> dict[str, str]:
    locs = json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8"))
    return {l["name"]: l.get("requires", "") for l in locs}


def test_boss_anchor_moons_require_boss_captures():
    reqs = _requires_by_name()
    for anchor, captures in EXPECTED_BOSS_CAPTURES.items():
        assert anchor in reqs, f"boss anchor moon missing from locations.json: {anchor}"
        for cap in captures:
            assert f"|{cap}|" in reqs[anchor], (
                f"{anchor}: boss capture |{cap}| missing from requires — the post-peace "
                f"/ moon-rock layer would be reachable without it (re-run "
                f"scripts/compile_moon_logic.py):\n  {reqs[anchor]!r}")


def test_peace_anchors_match_rules_functions():
    """Guards the propagation assumption: each EXPECTED anchor that is a Peace anchor is
    the exact location hooks/Rules.py::<Kingdom>Peace() calls canReachLocation on. If a
    Peace function is retargeted, the boss-capture gate must move with it."""
    rules_src = (APWORLD_ROOT / "hooks" / "Rules.py").read_text(encoding="utf-8")
    for anchor in (
        "Sand: The Hole in the Desert",
        "Lake: Broodals Over the Lake",
        "Wooded: Defend the Secret Flower Field!",
        "Metro: A Traditional Festival!",
        "Snow: The Bound Bowl Grand Prix",
        "Seaside: The Glass Is Half Full!",
        "Luncheon: Cookatiel Showdown!",
        "Bowser's: Showdown at Bowser's Castle",
        "Ruined: Battle with the Lord of Lightning!",
    ):
        assert anchor in rules_src, (
            f"peace anchor {anchor!r} not referenced in Rules.py — the {{Peace()}} "
            f"propagation the boss-capture gate relies on may be broken")
