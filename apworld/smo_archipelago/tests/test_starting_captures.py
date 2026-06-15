"""Tests for P2 starting-captures implementation.

Verifies three complementary layers:
  1. Data layer (items.json): Frog and Chain Chomp exist as Capture items,
     and the Capture pool has a third eligible item for the random slot.
  2. Source layer (hooks/World.py): FIXED_STARTER_CAPTURES is set correctly,
     _precollect_starting_captures removes items from the pool and calls
     push_precollected, and before_create_items_starting calls the function
     before any other pool mutation.
  3. Category-disable layer (hooks/Helpers.py): "Capture" category is
     unconditionally disabled so no Capture: X location enters the item fill.

Pure-data + source-parse (no Archipelago imports) — runs in the standard
test job without SMOAP_LIVE_AP.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _items() -> list[dict]:
    return json.loads(
        (APWORLD_ROOT / "data" / "items.json").read_text(encoding="utf-8")
    )


def _hooks_src(name: str) -> str:
    return (APWORLD_ROOT / "hooks" / name).read_text(encoding="utf-8")


def _capture_item_names() -> list[str]:
    """All item names in items.json whose category list includes 'Capture'."""
    return [
        it["name"]
        for it in _items()
        if "Capture" in it.get("category", [])
    ]


# ─── 1. Data layer: items.json ────────────────────────────────────────────────

def test_frog_exists_as_capture_item():
    names = _capture_item_names()
    assert "Frog" in names, (
        "items.json is missing a 'Frog' entry with category 'Capture'; "
        "it must be present so push_precollected can send it at game-start."
    )


def test_chain_chomp_exists_as_capture_item():
    names = _capture_item_names()
    assert "Chain Chomp" in names, (
        "items.json is missing a 'Chain Chomp' entry with category 'Capture'; "
        "it must be present so push_precollected can send it at game-start."
    )


def test_capture_pool_has_third_eligible_item():
    """The random starter slot needs at least one capture beyond Frog + Chain Chomp."""
    names = _capture_item_names()
    eligible = [n for n in names if n not in ("Frog", "Chain Chomp")]
    assert len(eligible) >= 1, (
        "No eligible capture item for the random starter slot "
        f"(pool={names!r}). Add a Capture item beyond Frog and Chain Chomp."
    )


def test_frog_and_chain_chomp_have_count_one():
    for it in _items():
        if it["name"] in ("Frog", "Chain Chomp"):
            assert int(it.get("count", 1)) == 1, (
                f"{it['name']} has count != 1; starting captures are singletons."
            )


# ─── 2. Source layer: hooks/World.py ─────────────────────────────────────────

def test_fixed_starter_captures_constant_defined():
    src = _hooks_src("World.py")
    assert "FIXED_STARTER_CAPTURES" in src, (
        "FIXED_STARTER_CAPTURES constant not found in hooks/World.py"
    )


def test_fixed_starter_captures_contains_frog_and_chain_chomp():
    src = _hooks_src("World.py")
    m = re.search(r'FIXED_STARTER_CAPTURES\s*[=:][^)]*\(([^)]+)\)', src)
    assert m, "Could not parse FIXED_STARTER_CAPTURES tuple in hooks/World.py"
    body = m.group(1)
    assert '"Frog"' in body or "'Frog'" in body, \
        "FIXED_STARTER_CAPTURES does not contain 'Frog'"
    assert '"Chain Chomp"' in body or "'Chain Chomp'" in body, \
        "FIXED_STARTER_CAPTURES does not contain 'Chain Chomp'"


def test_precollect_function_exists():
    src = _hooks_src("World.py")
    assert "def _precollect_starting_captures(" in src, (
        "_precollect_starting_captures function not found in hooks/World.py"
    )


def test_precollect_calls_push_precollected():
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_starting_captures\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_starting_captures body not found"
    body = m.group(1)
    assert "push_precollected" in body, (
        "_precollect_starting_captures must call multiworld.push_precollected "
        "for each starter so the AP server delivers them at game-start."
    )


def test_precollect_removes_items_from_pool():
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_starting_captures\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_starting_captures body not found"
    body = m.group(1)
    assert "item_pool.pop(" in body, (
        "_precollect_starting_captures must pop chosen items from item_pool "
        "so adjust_filler_items doesn't try to place them at locations."
    )


def test_precollect_chooses_random_extra():
    """A random third capture must be stored on world.random_starter_capture."""
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_starting_captures\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_starting_captures body not found"
    body = m.group(1)
    assert "random_starter_capture" in body, (
        "_precollect_starting_captures must set world.random_starter_capture "
        "for test introspection."
    )
    assert "world.random" in body, (
        "_precollect_starting_captures must use world.random (the seeded RNG) "
        "to pick the third capture, not the global random module."
    )


def test_before_create_items_starting_calls_precollect_first():
    """_precollect_starting_captures must be the first pool mutation in
    before_create_items_starting so the starters are present when removed."""
    src = _hooks_src("World.py")
    m = re.search(
        r"def before_create_items_starting\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_create_items_starting not found in hooks/World.py"
    body = m.group(1)
    assert "_precollect_starting_captures(" in body, (
        "before_create_items_starting must call _precollect_starting_captures"
    )
    # The precollect call must appear before any other substantive pool mutation
    # (the festival-goal trim). Check positional order in the body.
    precollect_pos = body.index("_precollect_starting_captures(")
    festival_pos = body.find("FESTIVAL_ITEMS_TO_DROP")
    if festival_pos != -1:
        assert precollect_pos < festival_pos, (
            "_precollect_starting_captures must run BEFORE the festival-goal "
            "trim so starter items are in the pool when removed."
        )


# ─── 3. Location-disable layer: hooks/Helpers.py ─────────────────────────────
#
# Regression guard (2026-06-14): capture ITEMS and capture LOCATIONS both carry
# category ["Capture"]. The retired-capturesanity disable MUST act on locations
# only — disabling the *category* zeroes out every capture item in create_items,
# making capture-gated locations unreachable (FillError on Puzzle Part /
# Picture Match Part). So the disable lives in before_is_location_enabled, NOT
# before_is_category_enabled, and categories.json must not gate "Capture" on the
# capturesanity option.

def test_capture_locations_disabled_in_helpers():
    """before_is_location_enabled must return False for Capture-category
    locations so no 'Capture: X' check is generated."""
    src = _hooks_src("Helpers.py")
    m = re.search(
        r"def before_is_location_enabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_is_location_enabled not found in hooks/Helpers.py"
    body = m.group(1)
    assert '"Capture"' in body or "'Capture'" in body, (
        "before_is_location_enabled does not reference the 'Capture' category"
    )
    # Look for the actual code gate (ignore comment mentions of "Capture"):
    # a `return False` guarded by a Capture category membership test.
    code_lines = [
        ln for ln in body.splitlines()
        if "Capture" in ln and not ln.lstrip().startswith("#")
    ]
    assert code_lines, (
        "before_is_location_enabled mentions 'Capture' only in comments — "
        "no code-level capture-location guard found."
    )
    assert "return False" in body, (
        "before_is_location_enabled does not return False for Capture locations; "
        f"body: {body!r}"
    )


def test_capture_category_not_disabled_for_items():
    """before_is_category_enabled must NOT blanket-disable 'Capture' — doing so
    drops every capture item from the pool. The only Capture handling allowed in
    the category hook is none (it's now a location-level concern)."""
    src = _hooks_src("Helpers.py")
    m = re.search(
        r"def before_is_category_enabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_is_category_enabled not found in hooks/Helpers.py"
    body = m.group(1)
    # No "Capture" early-return False may exist in the category hook.
    assert not re.search(
        r"==\s*[\"']Capture[\"']\s*:\s*\n?\s*return\s+False", body
    ), (
        "before_is_category_enabled still disables the 'Capture' category, which "
        "zeroes out capture items in create_items. Disable capture LOCATIONS in "
        "before_is_location_enabled instead."
    )


def test_capture_category_has_no_disabling_yaml_option():
    """categories.json 'Capture' must not be gated on the (deprecated)
    capturesanity option — that would disable capture items too."""
    cats = json.loads(
        (APWORLD_ROOT / "data" / "categories.json").read_text(encoding="utf-8")
    )
    cap = cats.get("Capture", {})
    assert "capturesanity" not in cap.get("yaml_option", []), (
        "categories.json 'Capture' is gated on 'capturesanity'; with the option "
        "off (default) this disables every capture item. Remove the yaml_option."
    )


# ─── 4. Precollect category-lookup regression ────────────────────────────────

def test_precollect_uses_name_table_not_item_data():
    """_precollect_starting_captures must resolve a capture's category from the
    world's name->data table, not a nonexistent it.item_data attribute (which
    silently matched nothing, leaving the starters unprecollected)."""
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_starting_captures\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_starting_captures body not found"
    body = m.group(1)
    assert "item_data" not in body, (
        "_precollect_starting_captures still references it.item_data, which "
        "SMOItem never sets — the category lookup will match nothing."
    )
    assert "item_name_to_item" in body, (
        "_precollect_starting_captures must resolve categories via "
        "world.item_name_to_item[name]."
    )


# ─── 5. no_logic testing option ──────────────────────────────────────────────

def test_no_logic_option_registered():
    src = (APWORLD_ROOT / "hooks" / "Options.py").read_text(encoding="utf-8")
    assert "class NoLogic(" in src, "NoLogic option class not defined in hooks/Options.py"
    assert 'options["no_logic"]' in src, (
        "no_logic not registered in before_options_defined"
    )


def test_no_logic_forces_access_rules_in_world():
    src = _hooks_src("World.py")
    assert "_apply_no_logic" in src, "_apply_no_logic not defined in hooks/World.py"
    m = re.search(
        r"def after_set_rules\b(.+?)(?=\n# |\ndef |\Z)", src, re.DOTALL,
    )
    assert m, "after_set_rules not found"
    assert 'is_option_enabled(multiworld, player, "no_logic")' in m.group(1), (
        "after_set_rules must call _apply_no_logic when no_logic is enabled"
    )
