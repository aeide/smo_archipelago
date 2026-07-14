"""Tests for the re-fight / Dark Side multi-moon BONUS side-grants.

Two layers, matching the suite's conventions:

  1. Behavioral (client/state.py, importable — no Archipelago deps): the new
     grant_bonus_* helpers + received_item_count bump the right counters, fold
     into the coin total and the ability snapshot, and a simulated ordered-chunk
     walk unlocks captures[0:3] then [3:6] across two Mushroom Kingdom Multi-Moon
     receipts. This exercises the load-bearing math the client relies on.

  2. Source-parse (client/context.py, hooks/World.py): the wiring — the bonus
     consumption is gated behind the reconnect-replay skip, indexes chunks from
     the authoritative mirror, folds abilities into the snapshot, and the
     generation roll + slot_data emit are present.

See docs/handoff-refight-multi-moons.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from client.protocol import ItemRef
from client.state import BridgeState, ItemEvent

APWORLD_ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = APWORLD_ROOT / "client"


def _client_src(name: str) -> str:
    return (CLIENT_ROOT / name).read_text(encoding="utf-8")


def _hooks_src(name: str) -> str:
    return (APWORLD_ROOT / "hooks" / name).read_text(encoding="utf-8")


def _fn_body(src: str, fn_name: str) -> str:
    m = re.search(
        r"(?:async\s+)?def " + re.escape(fn_name)
        + r"\b(.+?)(?=\n    (?:async\s+)?def |\nclass |\Z)",
        src, re.DOTALL,
    )
    assert m, f"{fn_name} not found in source"
    return m.group(1)


def _mm_event(name: str, kingdom: str) -> ItemEvent:
    return ItemEvent(item=ItemRef(
        kind="moon", kingdom=kingdom, shine_id="Multi-Moon", name=name))


# ------------------------------------------------ behavioral: state ---------

def test_grant_bonus_capture_bumps_counters_and_coins():
    s = BridgeState()
    s.grant_bonus_capture("Goomba")
    assert "Goomba" in s.captures_unlocked
    assert s.captures_received_count["Goomba"] == 1
    # First copy unlocks — no coins yet.
    assert s.compute_total_coin_grant() == 0
    # A duplicate bonus capture converts to 100 coins.
    s.grant_bonus_capture("Goomba")
    assert s.captures_received_count["Goomba"] == 2
    assert s.compute_total_coin_grant() == 100


def test_grant_bonus_ability_folds_into_snapshot_and_coins():
    s = BridgeState()
    s.grant_bonus_ability("Wall Slide")
    assert s.get_ability_counts()["Wall Slide"] == 1
    assert s.compute_total_coin_grant() == 0
    s.grant_bonus_ability("Wall Slide")  # duplicate -> coins
    assert s.get_ability_counts()["Wall Slide"] == 2
    assert s.compute_total_coin_grant() == 100


def test_bonus_capture_duplicate_of_real_capture_is_coins():
    """A bonus capture duplicating an already-received real capture converts to
    coins (the design's 'bonus on top; dupes fall through to coins')."""
    s = BridgeState()
    s.add_received_item(ItemEvent(item=ItemRef(kind="capture", cap="Frog")))
    assert s.compute_total_coin_grant() == 0
    s.grant_bonus_capture("Frog")
    assert s.compute_total_coin_grant() == 100


def test_ordered_chunk_walk_across_two_mushroom_mms():
    """Simulate the context's ordered-chunk consumption: the Nth Mushroom
    Kingdom Multi-Moon (counted from the mirror) consumes captures[3*(N-1):3*N].
    """
    s = BridgeState()
    bonus = [f"c{i}" for i in range(18)]

    # First Mushroom MM received.
    s.add_received_item(_mm_event("Mushroom Kingdom Multi-Moon", "Mushroom"))
    n = s.received_item_count("Mushroom Kingdom Multi-Moon")
    assert n == 1
    chunk1 = bonus[3 * (n - 1): 3 * n]
    assert chunk1 == ["c0", "c1", "c2"]
    for c in chunk1:
        s.grant_bonus_capture(c)

    # Second Mushroom MM received.
    s.add_received_item(_mm_event("Mushroom Kingdom Multi-Moon", "Mushroom"))
    n = s.received_item_count("Mushroom Kingdom Multi-Moon")
    assert n == 2
    chunk2 = bonus[3 * (n - 1): 3 * n]
    assert chunk2 == ["c3", "c4", "c5"]
    for c in chunk2:
        s.grant_bonus_capture(c)

    assert set(s.captures_unlocked) == set(bonus[:6])


def test_mm_still_grants_three_moons():
    """The Mushroom/Dark Side MM still weights +3 moons (kingdom classified via
    the ' Kingdom'-optional item regex — Dark Side has no 'Kingdom' token)."""
    s = BridgeState()
    s.add_received_item(_mm_event("Mushroom Kingdom Multi-Moon", "Mushroom"))
    assert s.moons_received_by_kingdom["Mushroom"] == 3
    s.add_received_item(_mm_event("Dark Side Multi-Moon", "Dark Side"))
    assert s.moons_received_by_kingdom["Dark Side"] == 3


def test_dark_side_multi_moon_item_classifies_as_moon():
    """The classifier must resolve 'Dark Side Multi-Moon' to a MOON with
    kingdom='Dark Side' despite the missing ' Kingdom' token, so it flows
    through the moon path (not ItemKind.OTHER)."""
    from client.datapackage import _ITEM_MOON_KINGDOM_RE
    m = _ITEM_MOON_KINGDOM_RE.match("Dark Side Multi-Moon")
    assert m and m.group(1) == "Dark Side" and m.group(2) == "Multi-Moon"
    # Regression guard: the kingdom form still parses correctly (non-greedy).
    m2 = _ITEM_MOON_KINGDOM_RE.match("Mushroom Kingdom Multi-Moon")
    assert m2 and m2.group(1) == "Mushroom"


# ----------------------------------------------- source-parse: wiring -------

def test_context_bonus_block_present_and_gated_behind_replay_skip():
    body = _fn_body(_client_src("context.py"), "_process_received_items")
    assert '"Mushroom Kingdom Multi-Moon"' in body
    assert '"Dark Side Multi-Moon"' in body
    assert "grant_bonus_capture" in body
    assert "grant_bonus_ability" in body
    assert "received_item_count" in body
    # Chunk indexing off the mirror count.
    assert "3 * (n - 1)" in body
    # Idempotency: the grant must sit AFTER the pos < initial_mirror_len skip.
    skip_idx = body.find("pos < initial_mirror_len")
    grant_idx = body.find("grant_bonus_capture")
    assert skip_idx != -1 and grant_idx != -1 and skip_idx < grant_idx, \
        "bonus grant must be gated behind the reconnect-replay skip"


def test_context_announces_bonus_via_cappy():
    """The in-game moon-get cutscene label has no room for the 3 bonus
    names (MAX_MOON_LABEL_BYTES=30), so the bonus grant must announce via
    the wider Cappy speech-bubble channel instead — one send_cappy call per
    branch, using format_bonus_grant_cappy, after the grant loop."""
    body = _fn_body(_client_src("context.py"), "_process_received_items")
    assert "format_bonus_grant_cappy" in body
    assert body.count("send_cappy") == 2
    # Both bonus branches must guard on having something to grant before
    # popping a Cappy bubble (format_bonus_grant_cappy("", []) is skippable,
    # but the guard also avoids an empty-list call in the capture branch,
    # which iterates a possibly-empty slice unlike the ability branch).
    mushroom_idx = body.find('"Mushroom Kingdom Multi-Moon"')
    dark_side_idx = body.find('"Dark Side Multi-Moon"')
    cappy_idx = body.find("send_cappy")
    second_cappy_idx = body.find("send_cappy", cappy_idx + 1)
    assert mushroom_idx != -1 and dark_side_idx != -1
    assert mushroom_idx < cappy_idx < dark_side_idx < second_cappy_idx, \
        "each MM branch must send its own Cappy bubble, not a shared one"


def test_context_imports_cappy_helpers():
    src = _client_src("context.py")
    assert "format_bonus_grant_cappy" in src
    assert "CappyMsg" in src


def test_context_reads_bonus_slot_data():
    src = _client_src("context.py")
    assert 'slot_data.get("mm_bonus_captures")' in src
    assert 'slot_data.get("mm_bonus_abilities")' in src
    assert "self.mm_bonus_captures" in src
    assert "self.mm_bonus_abilities" in src


def test_world_rolls_and_ships_bonus():
    src = _hooks_src("World.py")
    assert "def _roll_mm_bonus_grants" in src
    assert "MM_BONUS_CAPTURE_COUNT = 18" in src
    assert "MM_BONUS_ABILITY_COUNT = 3" in src
    assert "world.random.sample" in src
    slot = _fn_body(src, "before_fill_slot_data")
    assert '"mm_bonus_captures"' in slot and '"mm_bonus_abilities"' in slot
