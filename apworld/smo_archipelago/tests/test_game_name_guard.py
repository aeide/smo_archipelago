"""Tests for the RoomInfo / Connect game-name guard in SMOContext.

The AP server already rejects a Connect when its `game` field doesn't
match the slot's game (returns `ConnectionRefused` with `InvalidGame`).
The guard layered on top of that does two things:

1. **Proactive RoomInfo check** — when RoomInfo's `games` list doesn't
   contain "Spicy Meatball Overdrive" at all, `server_auth` refuses
   before sending Connect so the user gets a clear "wrong multiworld"
   message instead of a generic InvalidGame.

2. **Clearer ConnectionRefused messages** — when the server still
   refuses (e.g. slot-name typo into a different game's slot), the
   overridden `event_invalid_game` / `event_invalid_slot` name SMO and
   the attempted slot so the user knows which knob to turn.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _find_archipelago() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "vendor" / "Archipelago"
        if (cand / "CommonClient.py").exists():
            return cand
        worktrees = parent.parent
        if worktrees.name == "worktrees":
            main_cand = worktrees.parent.parent / "vendor" / "Archipelago"
            if (main_cand / "CommonClient.py").exists():
                return main_cand
    return None


_AP = _find_archipelago()
if _AP is not None and str(_AP) not in sys.path:
    sys.path.insert(0, str(_AP))

try:  # pragma: no cover
    import ModuleUpdate  # type: ignore[import-not-found]
    ModuleUpdate.update_ran = True
except ImportError:
    pass

pytest.importorskip(
    "CommonClient",
    reason="Archipelago checkout not present; init the vendor/Archipelago submodule.",
)

from CommonClient import CommonContext  # noqa: E402

from client.context import GAME_NAME, SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


def _make_ctx() -> SMOContext:
    return SMOContext(
        server_address=None,
        password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )


# ----- prepare_data_package stash --------------------------------------------


@pytest.mark.asyncio
async def test_prepare_data_package_stashes_games_set(monkeypatch):
    """Stash a defensive copy of the seed's games list before super() runs."""
    ctx = _make_ctx()

    # Avoid the real super().prepare_data_package trying to send_msgs (no
    # active websocket in tests). Empty checksums dict + no real socket are
    # fine because needed_updates ends up empty, so send_msgs isn't called.
    games = {"Spicy Meatball Overdrive", "A Link to the Past"}
    await ctx.prepare_data_package(games, {})

    # Should be present, and should be a defensive copy (super() mutates
    # `relevant_games` by adding "Archipelago" — we want OUR stash to
    # reflect the seed's actual games, not the augmented set).
    assert ctx._roominfo_games == {
        "Spicy Meatball Overdrive",
        "A Link to the Past",
    }
    # Defensive copy: mutating the caller's set doesn't bleed into ours.
    games.add("Some New Game")
    assert "Some New Game" not in ctx._roominfo_games


# ----- server_auth proactive guard -------------------------------------------


@pytest.mark.asyncio
async def test_server_auth_refuses_when_smo_missing_from_games_list():
    """When RoomInfo says the seed has no SMO slot at all, refuse before
    sending Connect — the AP server would reject InvalidGame anyway, but
    our message is clearer."""
    ctx = _make_ctx()
    ctx._roominfo_games = {"A Link to the Past", "Ocarina of Time"}

    with pytest.raises(Exception) as exc:
        await ctx.server_auth(password_requested=False)

    msg = str(exc.value)
    assert GAME_NAME in msg
    assert "does not include" in msg
    assert "A Link to the Past" in msg
    assert "Ocarina of Time" in msg
    # Suppress auto-reconnect so the GUI doesn't keep retrying a doomed dial.
    assert ctx.disconnected_intentionally is True


@pytest.mark.asyncio
async def test_server_auth_proceeds_when_smo_present(monkeypatch):
    """SMO is in the seed → send Connect normally."""
    ctx = _make_ctx()
    ctx._roominfo_games = {GAME_NAME, "A Link to the Past"}
    ctx.auth = "Mario"  # avoid get_username prompting on stdin

    send_connect_calls: list[dict] = []

    async def fake_send_connect(**kwargs):
        send_connect_calls.append(kwargs)

    async def fake_get_username():
        pass

    monkeypatch.setattr(ctx, "send_connect", fake_send_connect)
    monkeypatch.setattr(ctx, "get_username", fake_get_username)

    await ctx.server_auth(password_requested=False)

    assert len(send_connect_calls) == 1
    assert ctx.disconnected_intentionally is False


@pytest.mark.asyncio
async def test_server_auth_proceeds_when_no_roominfo_seen(monkeypatch):
    """Defensive: if _roominfo_games was never populated (no RoomInfo seen
    yet), don't block — let the AP server do the validation. RoomInfo
    arrives before server_auth in the real flow, so this shouldn't happen,
    but the guard shouldn't fail-closed on its own missing data."""
    ctx = _make_ctx()
    assert ctx._roominfo_games is None
    ctx.auth = "Mario"

    send_connect_calls: list[dict] = []

    async def fake_send_connect(**kwargs):
        send_connect_calls.append(kwargs)

    async def fake_get_username():
        pass

    monkeypatch.setattr(ctx, "send_connect", fake_send_connect)
    monkeypatch.setattr(ctx, "get_username", fake_get_username)

    await ctx.server_auth(password_requested=False)

    assert len(send_connect_calls) == 1


@pytest.mark.asyncio
async def test_server_auth_message_handles_empty_games_list():
    """Edge case: RoomInfo with an empty `games` list (shouldn't happen
    against a real AP server, but guard against IndexError-y crashes in
    the error path)."""
    ctx = _make_ctx()
    ctx._roominfo_games = set()

    with pytest.raises(Exception) as exc:
        await ctx.server_auth(password_requested=False)

    msg = str(exc.value)
    assert GAME_NAME in msg
    assert "(none)" in msg


# ----- ConnectionRefused message overrides -----------------------------------


@pytest.mark.asyncio
async def test_event_invalid_game_message_names_smo_and_slot():
    """When the AP server returns InvalidGame, the user should see a
    message that tells them WHICH game we tried to use and WHICH slot
    name we sent — not CommonContext's generic 'Invalid Game' line.

    (async so CommonContext.__init__ can spawn its keep_alive task.)"""
    ctx = _make_ctx()
    ctx.auth = "WrongSlotName"

    with pytest.raises(Exception) as exc:
        ctx.event_invalid_game()

    msg = str(exc.value)
    assert GAME_NAME in msg
    assert "'WrongSlotName'" in msg
    assert "different game" in msg
    assert "YAML" in msg  # nudges the user toward the fix


@pytest.mark.asyncio
async def test_event_invalid_slot_message_names_slot():
    """When the AP server returns InvalidSlot (no slot by that name in
    the seed), tell the user which name we sent so they can compare it
    against their YAML."""
    ctx = _make_ctx()
    ctx.auth = "TypoName"

    with pytest.raises(Exception) as exc:
        ctx.event_invalid_slot()

    msg = str(exc.value)
    assert "'TypoName'" in msg
    assert "no slot" in msg.lower()
    assert "YAML" in msg
