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
    Known exception: Metro has 2 MM items but only 1 taggable MM location
    ("A Traditional Festival!" is the festival victory location and can't
    hold an item), so before_create_items_filler drops one Metro MM from
    the pool when the option is on. This sync test catches any OTHER drift
    (a mistagged location) immediately."""
    mm_locs = Counter()
    for l in _locations():
        if l.get("multi_moon"):
            mm_locs[l["region"].replace(" Kingdom", "")] += 1

    mm_items = Counter()
    for i in _items():
        m = re.match(r"^(.+) Kingdom Multi-Moon$", i.get("name", ""))
        if m:
            mm_items[m.group(1)] += int(i.get("count", 1))

    expected = Counter(mm_items)
    expected["Metro"] -= 1  # the documented pool drop
    assert mm_locs == expected, (
        f"multi_moon location tags vs Multi-Moon item counts drift:\n"
        f"  locations: {dict(mm_locs)}\n  items-1Metro: {dict(expected)}")


def test_multi_moon_total_is_thirteen():
    assert sum(1 for l in _locations() if l.get("multi_moon")) == 13


def test_festival_victory_location_is_not_tagged():
    """The festival goal's victory location never holds a real item — it
    must NOT carry the multi_moon tag, or the matching is short one slot."""
    for l in _locations():
        if l.get("name") == "Metro: A Traditional Festival!":
            assert l.get("victory") is True
            assert not l.get("multi_moon")
            return
    raise AssertionError("festival victory location not found")


def test_world_drops_one_metro_mm_under_shuffle():
    src = _hooks_src("World.py")
    m = re.search(r"def before_create_items_filler\b.*?(?=\n# |\ndef )",
                  src, re.DOTALL)
    assert m, "before_create_items_filler not found"
    body = m.group(0)
    assert '"multi_moon_shuffle"' in body
    assert '"Metro Kingdom Multi-Moon"' in body and "pop" in body, \
        "one Metro Multi-Moon must be dropped to balance the MM matching"


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
