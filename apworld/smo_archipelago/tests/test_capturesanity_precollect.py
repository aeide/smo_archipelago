"""Tests for the capturesanity item-pool precollect fix (P5 doc §6.5, T4).

capturesanity OFF used to drop capture LOCATIONS only
(before_is_location_enabled) -- the capture ITEMS still rode the pool, so a
moon could hold e.g. Jizo with capturesanity off (Devon's find, 2026-07-09).
Fix mirrors the abilitysanity drop+precollect pair (see test_abilitysanity.py
/ docs/handoff-abilitysanity-precollect-fix.md), with one addition: the 3
fixed starters + 1 random starter capture are already precollected earlier
(before_create_items_starting -> _precollect_starting_captures), so the
mirror subtracts those from each name's already-precollected count instead of
double-precollecting.

Source-parse tests here run in the standard test job (no SMOAP_LIVE_AP).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APWORLD_ROOT = Path(__file__).resolve().parents[1]


def _items() -> list[dict]:
    return json.loads(
        (APWORLD_ROOT / "data" / "items.json").read_text(encoding="utf-8")
    )


def _hooks_src(name: str) -> str:
    return (APWORLD_ROOT / "hooks" / name).read_text(encoding="utf-8")


def _capture_item_names() -> list[str]:
    return [
        it["name"]
        for it in _items()
        if "Capture" in it.get("category", [])
    ]


# ─── Generation layer: drop helper ────────────────────────────────────────────

def test_capture_items_exist_in_pool():
    names = _capture_item_names()
    assert names, "no Capture-category items in items.json"
    assert "Frog" in names


def test_drop_capture_items_helper_defined():
    src = _hooks_src("World.py")
    assert "def _drop_capture_items_if_disabled(" in src, (
        "_drop_capture_items_if_disabled not found in hooks/World.py"
    )


def test_drop_capture_helper_gated_on_option_and_category():
    src = _hooks_src("World.py")
    m = re.search(
        r"def _drop_capture_items_if_disabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_drop_capture_items_if_disabled body not found"
    body = m.group(1)
    assert 'is_option_enabled(multiworld, player, "capturesanity")' in body, (
        "_drop_capture_items_if_disabled must check the capturesanity option"
    )
    assert "return" in body
    assert '"Capture"' in body, (
        "_drop_capture_items_if_disabled must filter the Capture category"
    )


def test_drop_capture_wired_into_before_create_items_filler():
    src = _hooks_src("World.py")
    m = re.search(
        r"def before_create_items_filler\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_create_items_filler body not found"
    assert "_drop_capture_items_if_disabled(" in m.group(1), (
        "before_create_items_filler must call _drop_capture_items_if_disabled"
    )


# ─── Generation layer: precollect helper ──────────────────────────────────────

def test_precollect_capture_helper_defined():
    src = _hooks_src("World.py")
    assert "def _precollect_capture_items_if_disabled(" in src, (
        "_precollect_capture_items_if_disabled not found in hooks/World.py"
    )


def test_precollect_capture_helper_gated_on_option_and_uses_unlock_count():
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_capture_items_if_disabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_capture_items_if_disabled body not found"
    body = m.group(1)
    assert 'is_option_enabled(multiworld, player, "capturesanity")' in body, (
        "_precollect_capture_items_if_disabled must check the capturesanity option"
    )
    assert "return" in body
    assert "push_precollected(" in body
    assert "unlock_count(" in body, (
        "_precollect_capture_items_if_disabled must precollect at the UNLOCK "
        "count (1 per capture), NOT the full items.json copy count — "
        "precollecting the pool-only clone copies mints spurious dup-coin "
        "grants on every boot (the sanity-OFF coin bug)"
    )
    assert '_names_in_item_category(world, "Capture")' in body


def test_precollect_capture_helper_subtracts_already_precollected_starters():
    """The 3 fixed + 1 random starter captures are precollected earlier
    (before_create_items_starting). The mirror must subtract those already-
    precollected copies per name, or the starters double-precollect into
    spurious dup-coin grants on the Switch."""
    src = _hooks_src("World.py")
    m = re.search(
        r"def _precollect_capture_items_if_disabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_precollect_capture_items_if_disabled body not found"
    body = m.group(1)
    assert "precollected_items" in body, (
        "_precollect_capture_items_if_disabled must read "
        "multiworld.precollected_items[player] to avoid double-precollecting "
        "the fixed/random starter captures"
    )


def test_precollect_capture_wired_into_before_create_items_filler():
    src = _hooks_src("World.py")
    m = re.search(
        r"def before_create_items_filler\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_create_items_filler body not found"
    body = m.group(1)
    assert "_precollect_capture_items_if_disabled(" in body, (
        "before_create_items_filler must call _precollect_capture_items_if_disabled"
    )
    assert "_drop_capture_items_if_disabled(" in body
