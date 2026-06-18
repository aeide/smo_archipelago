"""Consistency checks for the Moon Rock check locations (moon_rock_checks).

Pure-data + source-parse (no Archipelago imports), in the style of
test_kingdom_gates.py. The 127 rock-moon locations were sourced from the
Kgamer77/SuperMarioOdysseyArchipelago postgame tables (community lineage,
MIT) and audited one-by-one against the game's own IsMoonRock flag via
scripts/audit_moon_rock_locations.py — see scripts/moon_rock_candidates.json
for provenance. Moon Kingdom's 7 rock moons are deliberately EXCLUDED: its
story completes at the goal, so they could never be collected mid-run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]

# Audited per-kingdom rock-moon counts (the audit's ROCK + approved
# name-corrections). Any locations.json edit that drifts from this table
# should be a deliberate re-audit, not an accident.
EXPECTED_ROCK_COUNTS = {
    "Cap": 2, "Cascade": 4, "Sand": 6, "Lake": 2, "Wooded": 6,
    "Cloud": 2, "Lost": 4, "Metro": 8, "Seaside": 4, "Snow": 4,
    "Luncheon": 6, "Ruined": 2, "Bowser's": 4,
}
# NOTE: full audit target is 127 (see moon_rock_candidates.json + audit_moon_rock_locations.py).
# Currently 54 moon-pipe subareas have been added; the remaining 73 require
# running the romfs audit to identify which existing locations carry IsMoonRock.

# Kingdoms whose locations carry the post-metro category (festival-goal
# removal path).
POST_METRO = {"Snow", "Seaside", "Luncheon", "Ruined", "Bowser's"}

# items.json Power Moon counts AFTER the rock-moon bump (base + rock count).
EXPECTED_PM_COUNTS = {
    "Cap": 13, "Cascade": 23, "Sand": 66, "Lake": 28, "Wooded": 54,
    "Cloud": 3, "Lost": 25, "Metro": 59, "Snow": 37, "Seaside": 53,
    "Luncheon": 53, "Ruined": 5, "Bowser's": 41,
    # untouched: no rock checks for these
    "Moon": 14, "Mushroom": 1,
}


def _locations():
    return json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8"))


def _rock_locations():
    return [l for l in _locations() if "Moon Rock" in l.get("category", [])]


def test_rock_location_counts_match_audit():
    counts: dict[str, int] = {}
    for l in _rock_locations():
        kingdom = l["region"].replace(" Kingdom", "")
        counts[kingdom] = counts.get(kingdom, 0) + 1
    assert counts == EXPECTED_ROCK_COUNTS, (
        f"Moon Rock location counts drifted:\n  have: {counts}\n"
        f"  want: {EXPECTED_ROCK_COUNTS}")
    assert sum(counts.values()) == 54


def test_no_rock_locations_in_goal_kingdoms():
    """Moon (story ends at the goal) and Mushroom/Dark/Darker (out of scope)
    must have no rock-moon checks — they'd be uncollectable."""
    for l in _rock_locations():
        assert l["region"] not in (
            "Moon Kingdom", "Mushroom Kingdom", "Dark Side", "Darker Side"), \
            f"uncollectable rock location: {l['name']}"


def test_rock_locations_are_well_formed():
    """Region matches the kingdom category; post-metro kingdoms carry the
    festival-removal tag; every name uses the '<Kingdom>: ' prefix."""
    for l in _rock_locations():
        kingdom = l["region"].replace(" Kingdom", "")
        assert l["name"].startswith(f"{kingdom}: "), l["name"]
        assert f"{kingdom} Kingdom" in l["category"], l["name"]
        if kingdom in POST_METRO:
            assert "post-metro" in l["category"], (
                f"{l['name']}: post-metro tag missing (festival-goal removal)")
        else:
            assert "post-metro" not in l["category"], (
                f"{l['name']}: unexpected post-metro tag")


def test_pm_item_counts_include_rock_bump():
    items = json.loads(
        (APWORLD_ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    counts = {}
    for i in items:
        m = re.match(r"^(.+) Kingdom Power Moon$", i.get("name", ""))
        if m:
            counts[m.group(1)] = int(i.get("count", 1))
    assert counts == EXPECTED_PM_COUNTS, (
        f"Power Moon item counts drifted:\n  have: {counts}\n"
        f"  want: {EXPECTED_PM_COUNTS}")


def test_option_and_category_wired():
    opts = (APWORLD_ROOT / "hooks" / "Options.py").read_text(encoding="utf-8")
    assert "class MoonRockChecks(DefaultOnToggle)" in opts
    assert re.search(r'options\["moon_rock_checks"\]\s*=\s*MoonRockChecks', opts)

    cats = json.loads(
        (APWORLD_ROOT / "data" / "categories.json").read_text(encoding="utf-8"))
    assert cats.get("Moon Rock", {}).get("yaml_option") == ["moon_rock_checks"]
