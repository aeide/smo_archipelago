"""P3-3b client tests: ability classification + wire, duplicate->coins, and the
variant capture cap->hack override.

Behavioral where the module is import-safe (client.state / protocol / maps pull
no AP or Kivy deps), source-parse for the cross-module wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

from client.state import BridgeState, ItemEvent
from client.protocol import (
    AbilityStateMsg,
    ItemKind,
    ItemRef,
    decode,
    encode,
)
from client.maps import CaptureMap, VARIANT_CAP_HACK_OVERRIDE
from client.abilities import moves_owned, newly_unlocked_move, PROGRESSIVE_MOVES

CLIENT_ROOT = Path(__file__).resolve().parents[1] / "client"


def _src(filename: str) -> str:
    return (CLIENT_ROOT / filename).read_text(encoding="utf-8")


def _ability(name: str) -> ItemRef:
    return ItemRef(kind="ability", name=name)


def _capture(name: str) -> ItemRef:
    return ItemRef(kind="capture", cap=name)


def _cap_moon() -> ItemRef:
    return ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon")


# ── ItemKind + wire ───────────────────────────────────────────────────────────

def test_itemkind_ability_value():
    assert ItemKind.ABILITY.value == "ability"


def test_ability_state_round_trips():
    raw = encode(AbilityStateMsg(entries=[{"ability": "Backflip", "count": 1}]))
    d = decode(raw)
    assert d["t"] == "ability_state"
    assert d["entries"] == [{"ability": "Backflip", "count": 1}]


def test_ability_state_enforce_defaults_true():
    # abilitysanity ON: enforce defaults True (gates active on the Switch).
    d = decode(encode(AbilityStateMsg(entries=[])))
    assert d["enforce"] is True


def test_ability_state_enforce_false_when_abilitysanity_off():
    # abilitysanity OFF: enforce=False tells the Switch to open its gate.
    d = decode(encode(AbilityStateMsg(entries=[], enforce=False)))
    assert d["enforce"] is False


# ── State tracking ────────────────────────────────────────────────────────────

def test_ability_counts_tracked():
    s = BridgeState()
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_ability("Climb")))
    assert s.get_ability_counts() == {"Backflip": 2, "Climb": 1}


def test_snapshot_exposes_abilities_received():
    # The Odyssey-tab "Abilities owned" panel reads snapshot()["abilities_received"].
    s = BridgeState()
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_ability("Progressive Crouch")))
    s.add_received_item(ItemEvent(item=_ability("Progressive Crouch")))
    snap = s.snapshot()
    assert snap["abilities_received"] == {"Backflip": 1, "Progressive Crouch": 2}
    # Defensive copy — mutating the snapshot must not corrupt state.
    snap["abilities_received"]["Backflip"] = 99
    assert s.get_ability_counts()["Backflip"] == 1


# ── Ability -> move mapping (Odyssey list + unlock bubble) ────────────────────

def test_moves_owned_progressive_crouch_chain():
    assert moves_owned("Progressive Crouch", 1) == ["Crouch"]
    assert moves_owned("Progressive Crouch", 2) == ["Crouch", "Roll"]
    assert moves_owned("Progressive Crouch", 3) == ["Crouch", "Roll", "Roll Boost"]
    # Count past the chain (defensive) clamps, never errors.
    assert moves_owned("Progressive Crouch", 9) == ["Crouch", "Roll", "Roll Boost"]


def test_moves_owned_clone_levels_add_no_move():
    # Ground Pound chain has 2 real levels; a 3rd copy is a clone (coins).
    assert moves_owned("Progressive Ground Pound", 3) == ["Ground Pound", "Dive"]
    # Wall Slide chain has 1 real level; a 2nd copy is a clone.
    assert moves_owned("Wall Slide", 2) == ["Wall Slide"]


def test_moves_owned_single_grant_is_item_name():
    assert moves_owned("Ledge Grab", 1) == ["Ledge Grab"]
    # A clone of a single-grant ability adds no move.
    assert moves_owned("Ledge Grab", 2) == ["Ledge Grab"]
    assert moves_owned("Climb", 0) == []
    assert moves_owned("", 1) == []


def test_newly_unlocked_move_per_level():
    assert newly_unlocked_move("Progressive Crouch", 1) == "Crouch"
    assert newly_unlocked_move("Progressive Crouch", 2) == "Roll"
    assert newly_unlocked_move("Progressive Crouch", 3) == "Roll Boost"
    # Clone level past the chain -> no move (bubble falls back to coins).
    assert newly_unlocked_move("Progressive Ground Pound", 3) is None
    assert newly_unlocked_move("Wall Slide", 2) is None
    # Single-grant: only the first copy unlocks; clones return None.
    assert newly_unlocked_move("Backflip", 1) == "Backflip"
    assert newly_unlocked_move("Backflip", 2) is None


def test_progressive_table_matches_item_counts():
    # The chain lengths must not exceed the pool item counts in items.json,
    # or a player could never reach a listed move. (Clone copies make the
    # item count >= chain length, never less.)
    import json
    from pathlib import Path
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "items.json")
        .read_text(encoding="utf-8")
    )
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    counts = {it["name"]: it.get("count", 1) for it in items}
    for item_name, moves in PROGRESSIVE_MOVES.items():
        assert item_name in counts, f"{item_name} missing from items.json"
        assert counts[item_name] >= len(moves), (
            f"{item_name} count {counts[item_name]} < chain length {len(moves)}"
        )


def test_cpp_ability_move_table_mirrors_python():
    # ApState.cpp::abilityMoveAtLevel must carry the same item->moves table as
    # client/abilities.py (the source comment names abilities.py as the mirror).
    # Drift here = the in-game unlock bubble disagrees with the Odyssey list.
    src = (
        Path(__file__).resolve().parents[3]
        / "switch-mod" / "src" / "ap" / "ApState.cpp"
    ).read_text(encoding="utf-8")
    for item_name, moves in PROGRESSIVE_MOVES.items():
        assert f'"{item_name}"' in src, f"{item_name} chain missing from ApState.cpp"
        for move in moves:
            assert f'"{move}"' in src, f"move '{move}' missing from ApState.cpp"


def test_capture_counts_tracked_alongside_set():
    s = BridgeState()
    s.add_received_item(ItemEvent(item=_capture("Bullet Bill")))
    s.add_received_item(ItemEvent(item=_capture("Bullet Bill")))
    assert s.captures_unlocked == {"Bullet Bill"}
    assert s.captures_received_count == {"Bullet Bill": 2}


def test_total_coin_grant_folds_duplicates():
    s = BridgeState()
    # 2 Cap moons -> 200
    s.add_received_item(ItemEvent(item=_cap_moon()))
    s.add_received_item(ItemEvent(item=_cap_moon()))
    # Bullet Bill x2 -> 1 duplicate -> +100
    s.add_received_item(ItemEvent(item=_capture("Bullet Bill")))
    s.add_received_item(ItemEvent(item=_capture("Bullet Bill")))
    # Wall Slide x2 -> 1 duplicate -> +100
    s.add_received_item(ItemEvent(item=_ability("Wall Slide")))
    s.add_received_item(ItemEvent(item=_ability("Wall Slide")))
    # singles -> no duplicate coins
    s.add_received_item(ItemEvent(item=_capture("Goomba")))
    s.add_received_item(ItemEvent(item=_ability("Climb")))
    assert s.compute_total_coin_grant() == 200 + 100 + 100
    # compute_cap_coin_total stays Cap-only (unchanged contract)
    assert s.compute_cap_coin_total() == 200


def test_total_coin_grant_zero_when_no_duplicates():
    s = BridgeState()
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_capture("Goomba")))
    assert s.compute_total_coin_grant() == 0


# ── Variant cap->hack override ────────────────────────────────────────────────

def test_variant_cap_hack_override_resolves():
    cm = CaptureMap()  # empty table — override must still resolve the 4 variants
    assert cm.cap_to_hack("Puzzle Part (Lake Kingdom)") == "GotogotonLake"
    assert cm.cap_to_hack("Puzzle Part (Metro Kingdom)") == "GotogotonCity"
    assert cm.cap_to_hack("Picture Match Part (Goomba)") == "FukuwaraiFacePartsKuribo"
    assert cm.cap_to_hack("Picture Match Part (Mario)") == "FukuwaraiFacePartsMario"


def test_non_variant_cap_falls_through_to_identity():
    cm = CaptureMap()
    assert cm.cap_to_hack("Goomba") == "Goomba"


def test_override_covers_all_four_variants():
    assert set(VARIANT_CAP_HACK_OVERRIDE) == {
        "Puzzle Part (Lake Kingdom)",
        "Puzzle Part (Metro Kingdom)",
        "Picture Match Part (Goomba)",
        "Picture Match Part (Mario)",
    }


# ── Cross-module wiring (source-parse) ────────────────────────────────────────

def test_classify_item_has_ability_branch():
    src = _src("datapackage.py")
    assert '"ability" in cats' in src
    assert "ItemKind.ABILITY" in src


def test_switch_server_push_ability_state_defined():
    src = _src("switch_server.py")
    assert "async def push_ability_state" in src
    assert "AbilityStateMsg(" in src


def test_push_ability_state_in_hello_replay():
    src = _src("switch_server.py")
    m = re.search(
        r"async def _run_post_hello_replay\b.+?(?=\n    async def |\n    def )",
        src, re.DOTALL,
    )
    assert m, "_run_post_hello_replay not found"
    assert "push_ability_state" in m.group(0)


def test_push_coin_grant_uses_total_method():
    src = _src("switch_server.py")
    m = re.search(
        r"async def push_coin_grant\b.+?(?=\n    async def |\n    def )",
        src, re.DOTALL,
    )
    assert m, "push_coin_grant not found"
    assert "compute_total_coin_grant" in m.group(0)


def test_context_handles_ability_items():
    src = _src("context.py")
    assert "ItemKind.ABILITY.value" in src
    assert "push_ability_state" in src
