"""Tests for the multi_moon_shuffle option.

Pure-data + source-parse (no Archipelago imports), mirroring
test_kingdom_gates.py: the data invariants live in locations.json /
items.json, and the rule wiring is asserted against hooks/*.py source.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


def _locations():
    return json.loads(
        (APWORLD_ROOT / "data" / "locations.json").read_text(encoding="utf-8"))


def _items():
    return json.loads(
        (APWORLD_ROOT / "data" / "items.json").read_text(encoding="utf-8"))


def _hooks_src(name: str) -> str:
    return (APWORLD_ROOT / "hooks" / name).read_text(encoding="utf-8")


# ------------------------------------------------------- data invariants ----

def test_multi_moon_location_counts_match_item_counts():
    """The MM<->MM-location matching is only solvable if, per kingdom, the
    number of `multi_moon: true` locations equals the Multi-Moon item count.

    21<->21 since the re-fight/Dark Side bundle added 6 Mushroom + 1 Dark Side
    MM locations + items. Under the default (mushroom_kingdom) goal every MM
    location is a real check, so 21 items == 21 locations with no pool drop.
    Under the festival goal the Mushroom/Dark Side locations vanish and the
    festival is the victory location — before_create_items_filler drops the 7
    new MMs plus one Metro MM — but that's goal-conditional logic, not a static
    count mismatch, so we assert the raw counts match without any drop here."""
    mm_locs = Counter()
    for l in _locations():
        if l.get("multi_moon"):
            mm_locs[l["region"].replace(" Kingdom", "")] += 1

    mm_items = Counter()
    for i in _items():
        # " Kingdom" is optional so the Dark Side Multi-Moon (a non-kingdom
        # area) is counted under key "Dark Side", matching its region tag.
        m = re.match(r"^(.+?)(?: Kingdom)? Multi-Moon$", i.get("name", ""))
        if m:
            mm_items[m.group(1)] += int(i.get("count", 1))

    assert mm_locs == mm_items, (
        f"multi_moon location tags vs Multi-Moon item counts drift:\n"
        f"  locations: {dict(mm_locs)}\n  items: {dict(mm_items)}")


def test_multi_moon_total_is_twenty_one():
    """21 multi_moon locations: the 14 story-boss MMs (13 floating + festival)
    plus the 6 Mushroom Kingdom re-fights and the Dark Side arrival added by the
    re-fight/Dark Side bundle feature. Under the festival goal the 7 new ones
    vanish (post-Metro) and a Metro MM is dropped; under the default goal all 21
    are real checks."""
    assert sum(1 for l in _locations() if l.get("multi_moon")) == 21


def test_refight_and_dark_side_locations_tagged_multi_moon_not_junk():
    """The 6 Mushroom re-fights + Dark Side arrival must be multi_moon and must
    NOT be junk_only (the two rules conflict: junk_only rejects the very MM item
    the shuffle needs to place there)."""
    want = {
        "Mushroom: Tussle in Tostarena: Rematch",
        "Mushroom: Struggle in Steam Gardens: Rematch",
        "Mushroom: Dust-Up in New Donk City: Rematch",
        "Mushroom: Battle in Bubblaine: Rematch",
        "Mushroom: Blowup at Mount Volbono: Rematch",
        "Mushroom: Rumble in Crumbleden: Rematch",
        "Dark Side: Arrival at Rabbit Ridge!",
    }
    seen = set()
    for l in _locations():
        if l.get("name") in want:
            seen.add(l["name"])
            assert l.get("multi_moon") is True, f"{l['name']} not tagged multi_moon"
            assert not l.get("junk_only"), f"{l['name']} still junk_only"
    assert seen == want, f"missing tagged locations: {want - seen}"


def test_new_multi_moon_items_present():
    """The 6 Mushroom + 1 Dark Side Multi-Moon items back the 7 new locations."""
    by_name = {i["name"]: i for i in _items()}
    assert by_name["Mushroom Kingdom Multi-Moon"]["count"] == 6
    assert by_name["Dark Side Multi-Moon"]["count"] == 1


def test_festival_location_is_tagged_multi_moon():
    """The festival moon IS a real Multi-Moon boss fight; it must carry
    multi_moon: true so it can hold a Metro MM when the goal != festival."""
    for l in _locations():
        if l.get("name") == "Metro: A Traditional Festival!":
            assert l.get("victory") is True, "festival must still be a victory candidate"
            assert l.get("multi_moon") is True, "festival must be tagged multi_moon"
            return
    raise AssertionError("festival victory location not found")


def test_world_drops_one_metro_mm_only_under_festival_goal():
    """The Metro MM drop is conditional: festival goal → 13 items for 13
    fillable locations; default goal → 14 items for 14 locations (festival
    is a real check). The drop must be gated on goal == 1 (festival)."""
    src = _hooks_src("World.py")
    m = re.search(r"def before_create_items_filler\b.*?(?=\n# |\ndef )",
                  src, re.DOTALL)
    assert m, "before_create_items_filler not found"
    body = m.group(0)
    assert '"multi_moon_shuffle"' in body
    assert '"Metro Kingdom Multi-Moon"' in body and "pop" in body, \
        "one Metro Multi-Moon must be dropped (under festival goal) to balance the MM matching"
    assert 'goal' in body and '== 1' in body, \
        "Metro MM drop must be conditional on goal == 1 (festival), not always active"


def test_world_drops_new_mms_under_festival_goal():
    """Festival removes the post-Metro Mushroom/Dark Side locations, so the 6
    Mushroom + 1 Dark Side MM items must be dropped there too or they orphan the
    fill (under multi_moon_shuffle they're constrained to now-unreachable MM
    locations)."""
    src = _hooks_src("World.py")
    m = re.search(r"def before_create_items_filler\b.*?(?=\n# |\ndef )",
                  src, re.DOTALL)
    assert m, "before_create_items_filler not found"
    body = m.group(0)
    assert '"Mushroom Kingdom Multi-Moon"' in body and '"Dark Side Multi-Moon"' in body, \
        "festival drop must remove both new Multi-Moon items"
    assert "goal_is_festival" in body, \
        "the new-MM drop must be gated on the festival goal"


def test_bonus_grants_rolled_and_shipped():
    """18 bonus captures + 3 bonus abilities are rolled from world.random and
    emitted into slot_data as mm_bonus_captures / mm_bonus_abilities."""
    src = _hooks_src("World.py")
    assert "MM_BONUS_CAPTURE_COUNT = 18" in src
    assert "MM_BONUS_ABILITY_COUNT = 3" in src
    assert "def _roll_mm_bonus_grants" in src
    assert "world.random.sample" in src, "picks must come from the seeded RNG"
    # Rolled in after_create_items (alongside the kingdom-gate roll).
    m = re.search(r"def after_create_items\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m and "_roll_mm_bonus_grants" in m.group(0), \
        "after_create_items must roll the bonus grants"
    # Emitted in slot_data.
    m = re.search(r"def before_fill_slot_data\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m, "before_fill_slot_data not found"
    body = m.group(0)
    assert '"mm_bonus_captures"' in body and '"mm_bonus_abilities"' in body, \
        "slot_data must carry both bonus lists"


def test_ruined_pin_is_a_tagged_mm_location():
    """The pinned dragon location must itself be multi_moon-tagged, or the
    place_item would violate the matching."""
    for l in _locations():
        if l.get("place_item") == ["Ruined Kingdom Multi-Moon"]:
            assert l.get("multi_moon") is True
            return
    raise AssertionError("Ruined Multi-Moon place_item pin not found")


def test_cascade_mm_location_is_filler_only_and_tagged():
    """Documents the constraint that forced the PM-first demotion strategy:
    this location is both multi_moon (only MM items) and filler_only (no
    progression items), so a demoted Multi-Moon must always exist."""
    for l in _locations():
        if l.get("name") == "Cascade: Multi Moon Atop the Falls":
            assert l.get("multi_moon") is True
            assert l.get("filler_only") is True
            return
    raise AssertionError("Cascade MM location not found")


# ------------------------------------------------------------ wiring  -------

def test_option_registered():
    src = _hooks_src("Options.py")
    assert "class MultiMoonShuffle(DefaultOnToggle)" in src
    assert re.search(
        r'options\["multi_moon_shuffle"\]\s*=\s*MultiMoonShuffle', src)


def test_rules_applied_in_after_set_rules():
    src = _hooks_src("World.py")
    m = re.search(r"def after_set_rules\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m, "after_set_rules not found"
    assert "_apply_multi_moon_rules" in m.group(0)
    assert '"multi_moon_shuffle"' in m.group(0)


def test_demotion_prefers_demoting_multimoons_under_shuffle():
    src = _hooks_src("World.py")
    assert "prefer_demoting_multimoons" in src
    m = re.search(r"def after_create_items\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m and "prefer_demoting_multimoons=is_option_enabled" in m.group(0), \
        "after_create_items does not flip demotion strategy with the option"


def test_ruined_exempt_from_demotion():
    src = _hooks_src("World.py")
    m = re.search(r"def _demote_surplus_kingdom_moons\b.*?(?=\ndef )", src, re.DOTALL)
    assert m, "_demote_surplus_kingdom_moons not found"
    assert 'if kingdom == "Ruined"' in m.group(0), \
        "Ruined kingdom must be exempt from progression demotion"


def test_mm_rule_uses_item_name_suffix():
    """The matching keys off the ' Multi-Moon' name suffix; if item naming
    ever changes, this and the rule must move together."""
    src = _hooks_src("World.py")
    m = re.search(r"def _apply_multi_moon_rules\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m, "_apply_multi_moon_rules not found"
    assert '" Multi-Moon"' in m.group(0)
    assert "add_item_rule" in m.group(0)
