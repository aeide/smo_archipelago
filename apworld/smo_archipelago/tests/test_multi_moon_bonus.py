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

import asyncio
import json
import re
from pathlib import Path

import pytest

from client import protocol
from client.abilities import newly_unlocked_move
from client.display import format_bonus_grant_cappy
from client.protocol import HelloMsg, ItemRef
from client.state import BridgeState, ItemEvent
from client.switch_server import SwitchServer

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


def _simulate_dark_side_toast(s: BridgeState, bonus_abilities: list[str]) -> str:
    """Replicate the context.py Dark Side branch's translation math exactly
    (prior-count read before grant, newly_unlocked_move, fallback to the raw
    item name), without going through SMOContext. Mirrors how the MK chunk-
    walk above is simulated at the state layer."""
    granted_moves = []
    for ab in bonus_abilities:
        prior = s.abilities_received.get(ab, 0)
        move = newly_unlocked_move(ab, prior + 1)
        granted_moves.append(move or ab)
        s.grant_bonus_ability(ab)
    return format_bonus_grant_cappy("Bonus abilities", granted_moves)


def test_dark_side_toast_shows_concrete_move_not_pool_item_name():
    """The player thinks in terms of moves, not pool item names — a bonus
    grant of 'Progressive Crouch' should announce 'Crouch', matching the
    Odyssey-tab convention (abilities.py module docstring) and the real
    ability receipt's moon-label rewrite (context.py ~line 1681)."""
    s = BridgeState()
    text = _simulate_dark_side_toast(s, ["Progressive Crouch", "Wall Slide", "Climb"])
    assert text == "Bonus abilities: Crouch, Wall Slide, Climb"


def test_dark_side_toast_translates_second_progressive_level():
    """A player who already owns the first level of a progressive chain (via
    the real pool) and then receives that SAME item as a bonus grant should
    see the next move in the chain, not a repeat of the first."""
    s = BridgeState()
    s.abilities_received["Progressive Crouch"] = 1  # real receipt: Crouch owned
    text = _simulate_dark_side_toast(s, ["Progressive Crouch"])
    assert text == "Bonus abilities: Roll"


def test_dark_side_toast_falls_back_to_item_name_past_chain_end():
    """A bonus grant of an item whose chain is already fully owned unlocks no
    new move (newly_unlocked_move returns None) — the toast must fall back to
    the raw item name rather than silently drop the entry or show 'None'."""
    s = BridgeState()
    s.abilities_received["Progressive Crouch"] = 3  # Crouch/Roll/Roll Boost all owned
    text = _simulate_dark_side_toast(s, ["Progressive Crouch"])
    assert text == "Bonus abilities: Progressive Crouch"


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


# -------------------------------- behavioral: HELLO replay (the regression) --

async def _drain_messages(reader: asyncio.StreamReader, n: int,
                          timeout: float) -> list[dict]:
    """Read until n full JSON lines are parsed or timeout expires."""
    buf = bytearray()
    out: list[dict] = []

    async def _pump():
        while len(out) < n:
            chunk = await reader.read(4096)
            if not chunk:
                return
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = bytes(buf[:nl]).strip()
                del buf[: nl + 1]
                if line:
                    out.append(json.loads(line))
                    if len(out) >= n:
                        return

    await asyncio.wait_for(_pump(), timeout=timeout)
    return out


async def _hello_and_drain(state: BridgeState, n: int) -> list[dict]:
    """Run a real HELLO handshake against a loopback SwitchServer and return
    the first `n` replayed messages. Defaults mirror a live seed: capturesanity
    and abilitysanity ON, so nothing is synthesized wholesale."""
    async def on_check(_): return None
    async def on_goal(): ...

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await writer.drain()
        return await _drain_messages(reader, n=n, timeout=2.0)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_hello_replay_ships_bonus_captures():
    """THE regression (Devon, 2026-07-17: bonus-granted Volbonan showed unlocked
    in the tracker but still ejected Mario in-game).

    The Switch resets captures_unlocked on every save load (SaveLoadHook.cpp)
    and rebuilds it from the HELLO replay. That replay walks received_items —
    and a bonus capture has no entry there (grant_bonus_capture is a side-effect
    of a Multi-Moon, not a real item), while the Multi-Moon that triggered it IS
    in the mirror but is skipped as a Moon by M6 phase D. So pre-fix the live
    send_item at grant time was the ONLY delivery and the first save load
    silently re-locked the capture. Covers the offline case too: the grant here
    happens with no Switch attached, exactly as when a MM arrives before HELLO.
    """
    state = BridgeState()
    # The Multi-Moon that triggered the bonus: in the mirror, and a Moon.
    state.add_received_item(_mm_event("Mushroom Kingdom Multi-Moon", "Mushroom"))
    for cap, hack in [("Volbonan", "Volbonan"),
                      ("Goomba", "Kuribo"),
                      ("T-Rex", "TRex")]:
        state.grant_bonus_capture(cap, hack)

    # hello_ack + checked_replay + 3 bonus items + ap_state. The Multi-Moon
    # itself must NOT be replayed (M6 phase D) — a 4th item would mean the
    # Moon-replay-skip regressed and per-kingdom moon credit is double-counting.
    msgs = await _hello_and_drain(state, n=6)
    assert [m["t"] for m in msgs] == [
        "hello_ack", "checked_replay", "item", "item", "item", "ap_state"]

    items = [m for m in msgs if m["t"] == "item"]
    by_cap = {m["cap"]: m for m in items}
    assert set(by_cap) == {"Volbonan", "Goomba", "T-Rex"}
    for m in items:
        assert m["kind"] == "capture"
        # Silent: the player saw the bonus announced when the MM landed; a
        # save load must not re-announce all 18. (The encoder strips empty
        # fields, so the key may be absent entirely.)
        assert m.get("from", "") == ""
    # hack_name is what CaptureGate matches on — an unmapped name fails open.
    assert by_cap["Goomba"]["hack_name"] == "Kuribo"
    assert by_cap["T-Rex"]["hack_name"] == "TRex"


@pytest.mark.asyncio
async def test_hello_replay_ships_bonus_abilities_via_snapshot():
    """The Dark Side MM's bonus ABILITIES have no equivalent gap: they ride
    push_ability_state's full per-ability count snapshot, which is derived from
    abilities_received (what grant_bonus_ability bumps) rather than replayed
    from the item mirror. This test pins that asymmetry — it is the reason the
    fix is capture-side only. See docs/handoff-mm-bonus-capture-enforcement.md.
    """
    state = BridgeState()
    state.add_received_item(_mm_event("Dark Side Multi-Moon", "Dark Side"))
    for ab in ["Wall Slide", "Cap Bounce", "Spin Throw"]:
        state.grant_bonus_ability(ab)

    # hello_ack + checked_replay + ability_state + ap_state.
    msgs = await _hello_and_drain(state, n=4)
    snap = [m for m in msgs if m["t"] == "ability_state"]
    assert len(snap) == 1, "bonus abilities must ride the HELLO ability snapshot"
    assert {e["ability"] for e in snap[0]["entries"]} == {
        "Wall Slide", "Cap Bounce", "Spin Throw"}


@pytest.mark.asyncio
async def test_hello_replay_of_bonus_captures_does_not_mint_coins():
    """Re-shipping bonus captures on every HELLO must not look like duplicate
    receipts. The replay only writes the wire — it never re-enters
    grant_bonus_capture — so captures_received_count stays at 1 apiece and
    compute_total_coin_grant stays 0 across reconnects."""
    state = BridgeState()
    state.grant_bonus_capture("Volbonan", "Volbonan")
    assert state.compute_total_coin_grant() == 0

    for _ in range(3):  # three save loads / reconnects
        await _hello_and_drain(state, n=4)  # hello_ack, checked_replay, item, ap_state

    assert state.captures_received_count["Volbonan"] == 1
    assert state.compute_total_coin_grant() == 0


# ------------------------------------------- behavioral: bonus store --------

def test_grant_bonus_capture_records_hack_name_for_replay():
    s = BridgeState()
    s.grant_bonus_capture("Goomba", "Kuribo")
    assert s.all_bonus_captures() == [("Goomba", "Kuribo")]
    # A duplicate bonus still bumps the coin-bearing count, but the replay
    # store is presence-keyed — it must not grow a second row.
    s.grant_bonus_capture("Goomba", "Kuribo")
    assert s.all_bonus_captures() == [("Goomba", "Kuribo")]
    assert s.captures_received_count["Goomba"] == 2


def test_clear_received_resets_bonus_captures():
    """Slot change: the new slot rolls its own mm_bonus_captures, so the prior
    slot's picks must not keep re-shipping on every HELLO replay."""
    s = BridgeState()
    s.grant_bonus_capture("Goomba", "Kuribo")
    s.clear_received()
    assert s.all_bonus_captures() == []
    assert s.captures_unlocked == set()


# ----------------------------------------------- source-parse: wiring -------

def test_hello_replay_pushes_bonus_captures():
    body = _fn_body(_client_src("switch_server.py"), "_run_post_hello_replay")
    assert "push_bonus_captures" in body, \
        "_run_post_hello_replay must re-ship bonus captures or a save load re-locks them"
    # M6 phase D guard: the fix must not have reached for the easy wrong lever
    # (replaying the Multi-Moon itself), which would double-count moon credit.
    assert 'if evt.item.kind == "moon":' in body and "continue" in body, \
        "the Moon-replay-skip invariant must stay intact"


def test_context_passes_hack_name_to_grant_bonus_capture():
    """CaptureGate matches on the SMO-internal hack_name, so the grant must
    record one — a bare grant_bonus_capture(cap) would replay an unmatched
    name and fail open."""
    body = _fn_body(_client_src("context.py"), "_process_received_items")
    assert re.search(r"grant_bonus_capture\(\s*cap\s*,\s*hack_name\s*\)", body), \
        "context must pass the resolved hack_name into grant_bonus_capture"


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


def test_context_dark_side_toast_translates_via_newly_unlocked_move():
    """The Dark Side branch must announce concrete move names, not raw pool
    item names — mirrors the real ability receipt's moon-label rewrite
    (context.py ~line 1681), which uses the identical
    prior/newly_unlocked_move/fallback idiom."""
    body = _fn_body(_client_src("context.py"), "_process_received_items")
    ds_idx = body.find('"Dark Side Multi-Moon"')
    assert ds_idx != -1
    ds_body = body[ds_idx:]
    assert "newly_unlocked_move" in ds_body
    assert "granted_moves" in ds_body
    # format_bonus_grant_cappy must receive the translated list, not the raw
    # slot_data item names (self.mm_bonus_abilities).
    assert 'format_bonus_grant_cappy("Bonus abilities", granted_moves)' in ds_body
    # `prior` must be read from abilities_received BEFORE grant_bonus_ability
    # mutates it in place, same ordering requirement as the capture branch's
    # hack_name-before-grant.
    prior_idx = ds_body.find("abilities_received.get")
    grant_idx = ds_body.find("grant_bonus_ability")
    assert prior_idx != -1 and grant_idx != -1 and prior_idx < grant_idx, \
        "prior count must be read before grant_bonus_ability mutates it"


def test_context_imports_newly_unlocked_move():
    assert "from .abilities import newly_unlocked_move" in _client_src("context.py")


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
