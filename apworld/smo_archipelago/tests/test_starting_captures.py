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


# ─── 3. Category-disable layer: hooks/Helpers.py ─────────────────────────────

def test_capture_category_disabled_in_helpers():
    """before_is_category_enabled must return False for 'Capture' so no
    Capture: X location is generated — the items go through starting
    inventory only."""
    src = _hooks_src("Helpers.py")
    m = re.search(
        r"def before_is_category_enabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_is_category_enabled not found in hooks/Helpers.py"
    body = m.group(1)
    assert '"Capture"' in body or "'Capture'" in body, (
        "before_is_category_enabled does not reference the 'Capture' category"
    )
    # The guard must return False, not None or True.
    # Find the Capture block and confirm False follows.
    capture_idx = body.find('"Capture"') if '"Capture"' in body else body.find("'Capture'")
    excerpt = body[capture_idx: capture_idx + 120]
    assert "return False" in excerpt, (
        "before_is_category_enabled does not return False for 'Capture'; "
        f"excerpt: {excerpt!r}"
    )


def test_capture_category_check_precedes_shared_peace_check():
    """The Capture guard must come before the SHARED_PEACE_CATEGORY guard
    (no functional reason, but ensures it's not accidentally buried after
    the peace logic)."""
    src = _hooks_src("Helpers.py")
    m = re.search(
        r"def before_is_category_enabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_is_category_enabled not found in hooks/Helpers.py"
    body = m.group(1)
    cap_idx = body.find('"Capture"') if '"Capture"' in body else body.find("'Capture'")
    peace_idx = body.find("SHARED_PEACE_CATEGORY")
    assert cap_idx != -1, "'Capture' check missing from before_is_category_enabled"
    if peace_idx != -1:
        assert cap_idx < peace_idx, (
            "The 'Capture' early-return must precede the SHARED_PEACE_CATEGORY block"
        )
