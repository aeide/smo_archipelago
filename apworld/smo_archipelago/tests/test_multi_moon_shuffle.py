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

    Under the default (mushroom_kingdom) goal "Metro: A Traditional Festival!"
    is a real 14th MM location, so 14 items == 14 locations with no pool drop.
    Under the festival goal the festival is the victory location (can't hold
    an item), so before_create_items_filler drops one Metro MM giving 13 items
    for 13 locations — but that's goal-conditional logic, not a static count
    mismatch, so we assert the raw counts match without any drop here."""
    mm_locs = Counter()
    for l in _locations():
        if l.get("multi_moon"):
            mm_locs[l["region"].replace(" Kingdom", "")] += 1

    mm_items = Counter()
    for i in _items():
        m = re.match(r"^(.+) Kingdom Multi-Moon$", i.get("name", ""))
        if m:
            mm_items[m.group(1)] += int(i.get("count", 1))

    assert mm_locs == mm_items, (
        f"multi_moon location tags vs Multi-Moon item counts drift:\n"
        f"  locations: {dict(mm_locs)}\n  items: {dict(mm_items)}")


def test_multi_moon_total_is_fourteen():
    """14 multi_moon locations: 13 floating + festival (real MM boss fight).
    Under festival goal the festival becomes victory and before_create_items_filler
    drops one Metro MM, giving 13 items for 13 locations. Under the default goal
    the festival is a normal 14th MM check holding the second Metro MM."""
    assert sum(1 for l in _locations() if l.get("multi_moon")) == 14


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
