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


# ── State tracking ────────────────────────────────────────────────────────────

def test_ability_counts_tracked():
    s = BridgeState()
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_ability("Backflip")))
    s.add_received_item(ItemEvent(item=_ability("Climb")))
    assert s.get_ability_counts() == {"Backflip": 2, "Climb": 1}


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
