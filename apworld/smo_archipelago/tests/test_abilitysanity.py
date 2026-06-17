"""Tests for the abilitysanity option (ability-shuffle opt-out).

abilitysanity (default ON, mirrors capturesanity) gates ALL ability-shuffle
work behind a single flag:
  1. Options layer (hooks/Options.py): AbilitySanity is defined + registered.
  2. Generation layer (hooks/World.py): when OFF, the Ability-category items
     are dropped from the pool (adjust_filler_items tops up with filler), and
     this runs inside before_create_items_filler.
  3. Wire layer: the AbilityStateMsg carries an `enforce` flag so the Switch
     opens its ability gate when abilitysanity is off (tested in
     test_ability_wire.py for the message; here we assert the client wiring
     reads abilitysanity from slot_data and pushes it).

Pure source-parse + data (no Archipelago imports) — runs in the standard
test job without SMOAP_LIVE_AP.
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


def _client_src(name: str) -> str:
    return (APWORLD_ROOT / "client" / name).read_text(encoding="utf-8")


def _ability_item_names() -> list[str]:
    return [
        it["name"]
        for it in _items()
        if "Ability" in it.get("category", [])
    ]


# ─── 1. Options layer ─────────────────────────────────────────────────────────

def test_abilitysanity_option_defined():
    src = _hooks_src("Options.py")
    assert "class AbilitySanity(DefaultOnToggle):" in src, (
        "AbilitySanity option class not found in hooks/Options.py"
    )


def test_abilitysanity_option_registered():
    src = _hooks_src("Options.py")
    assert 'options["abilitysanity"] = AbilitySanity' in src, (
        "abilitysanity not registered in before_options_defined"
    )


# ─── 2. Generation layer ──────────────────────────────────────────────────────

def test_ability_items_exist_in_pool():
    # Sanity: there must be Ability-category items for the option to gate.
    names = _ability_item_names()
    assert names, "no Ability-category items in items.json"
    assert "Progressive Jump" in names


def test_drop_ability_items_helper_defined():
    src = _hooks_src("World.py")
    assert "def _drop_ability_items_if_disabled(" in src, (
        "_drop_ability_items_if_disabled not found in hooks/World.py"
    )


def test_drop_ability_helper_gated_on_option_and_category():
    src = _hooks_src("World.py")
    m = re.search(
        r"def _drop_ability_items_if_disabled\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "_drop_ability_items_if_disabled body not found"
    body = m.group(1)
    # Must be a no-op when abilitysanity is enabled (early return).
    assert 'is_option_enabled(multiworld, player, "abilitysanity")' in body, (
        "_drop_ability_items_if_disabled must check the abilitysanity option"
    )
    assert "return" in body
    # Must filter on the Ability category.
    assert '"Ability"' in body, (
        "_drop_ability_items_if_disabled must filter the Ability category"
    )


def test_drop_ability_wired_into_before_create_items_filler():
    src = _hooks_src("World.py")
    m = re.search(
        r"def before_create_items_filler\b(.+?)(?=\n# |\ndef |\Z)",
        src, re.DOTALL,
    )
    assert m, "before_create_items_filler body not found"
    assert "_drop_ability_items_if_disabled(" in m.group(1), (
        "before_create_items_filler must call _drop_ability_items_if_disabled"
    )


# ─── 3. Client wiring ─────────────────────────────────────────────────────────

def test_context_reads_abilitysanity_from_slot_data():
    src = _client_src("context.py")
    assert 'slot_data.get("abilitysanity"' in src, (
        "context.py must read abilitysanity from slot_data"
    )
    assert "set_abilitysanity_enabled(" in src, (
        "context.py must propagate abilitysanity to the SwitchServer"
    )


def test_switch_server_has_abilitysanity_setter_and_enforce():
    src = _client_src("switch_server.py")
    assert "def set_abilitysanity_enabled(" in src, (
        "switch_server.py must define set_abilitysanity_enabled"
    )
    # push_ability_state must send the enforce flag.
    assert "enforce=enforce" in src, (
        "push_ability_state must pass enforce to AbilityStateMsg"
    )
