"""Tests for SMOContext.connect / disconnect behavior.

Earlier builds parked the AP dial behind a Switch-presence gate (SNI-style):
the user clicked Connect and we deferred the websocket dial until the Switch
HELLO'd. That blocked the user from validating creds without booting SMO, so
the gate was ripped. These tests now pin the new behavior: Connect dials AP
immediately, disconnect cleans up regardless of Switch presence, and a Switch
HELLO has no AP-side side effect.
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
from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


class _StubSwitch:
    """Just enough surface area for connect/disconnect testing."""

    def __init__(self, connected: bool = False) -> None:
        self._connected = connected
        self.items: list = []
        self.kills: list = []
        self.prints: list = []
        self.ap_states: list = []

    def is_connected(self) -> bool:
        return self._connected

    async def send_item(self, item) -> None:  # pragma: no cover - unused
        self.items.append(item)

    async def send_kill(self, k) -> None:  # pragma: no cover - unused
        self.kills.append(k)

    async def send_print(self, text: str) -> None:  # pragma: no cover - unused
        self.prints.append(text)

    async def send_ap_state(self, conn: str) -> None:
        self.ap_states.append(conn)

    def set_capturesanity_enabled(self, enabled: bool) -> None:  # pragma: no cover - unused here
        pass

    async def push_capturesanity_replay(self) -> None:  # pragma: no cover - unused here
        pass

    def set_deathlink_enabled(self, enabled: bool) -> None:  # pragma: no cover - unused here
        pass

    async def push_deathlink_helloack(self) -> None:  # pragma: no cover - unused here
        pass


def _make_ctx(switch_connected: bool) -> tuple[SMOContext, BridgeState, _StubSwitch]:
    state = BridgeState()
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=state,
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    sw = _StubSwitch(connected=switch_connected)
    ctx.switch = sw  # type: ignore[assignment]
    return ctx, state, sw


async def _record(sink, address):
    sink.append(address)


async def _record_bool(sink, val):
    sink.append(val)


# ---- eager dial -----------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_dials_immediately_without_switch(monkeypatch):
    """No Switch attached → Connect still dials AP. Lets the user validate
    creds (and watch items flow into the log) before booting SMO."""
    ctx, _state, _sw = _make_ctx(switch_connected=False)
    super_calls: list[str | None] = []
    monkeypatch.setattr(CommonContext, "connect", lambda self, address=None: _record(super_calls, address))

    await ctx.connect("localhost:38281")

    assert super_calls == ["localhost:38281"]
    assert ctx.server_address == "localhost:38281"  # GUI prefill persists


@pytest.mark.asyncio
async def test_connect_dials_immediately_with_switch(monkeypatch):
    """Switch already up → same path, dial AP. (No branching on switch state.)"""
    ctx, _state, _sw = _make_ctx(switch_connected=True)
    super_calls: list[str | None] = []
    monkeypatch.setattr(CommonContext, "connect", lambda self, address=None: _record(super_calls, address))

    await ctx.connect("localhost:38281")

    assert super_calls == ["localhost:38281"]
    assert ctx.server_address == "localhost:38281"


@pytest.mark.asyncio
async def test_connect_clears_intentional_disconnect_flag(monkeypatch):
    """CommonContext sets disconnected_intentionally=True on a manual /disconnect;
    a subsequent Connect must clear it or the reconnect loop refuses to fire."""
    ctx, _state, _sw = _make_ctx(switch_connected=False)
    monkeypatch.setattr(CommonContext, "connect", lambda self, address=None: _record([], address))
    ctx.disconnected_intentionally = True

    await ctx.connect("localhost:38281")

    assert ctx.disconnected_intentionally is False


# ---- disconnect -----------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_from_ready_pushes_ap_state_to_switch(monkeypatch):
    """Disconnect while AP was 'ready' broadcasts 'disconnected' to the Switch
    so the CappyMessenger fires a 'Disconnected from Archipelago' bubble on
    the ready -> disconnected transition."""
    ctx, state, sw = _make_ctx(switch_connected=True)
    monkeypatch.setattr(
        CommonContext,
        "disconnect",
        lambda self, allow_autoreconnect=False: _record_bool([], allow_autoreconnect),
    )

    state.set_ap_conn("ready")
    sw.ap_states.clear()

    await ctx.disconnect()

    assert state.ap_conn == "disconnected"
    assert sw.ap_states == ["disconnected"]


@pytest.mark.asyncio
async def test_disconnect_when_already_disconnected_is_silent(monkeypatch):
    """A no-op disconnect (already 'disconnected') must not push another
    ap_state to the Switch — keeps reconnect-loop churn off the bubble queue."""
    ctx, state, sw = _make_ctx(switch_connected=True)
    monkeypatch.setattr(
        CommonContext,
        "disconnect",
        lambda self, allow_autoreconnect=False: _record_bool([], allow_autoreconnect),
    )

    assert state.ap_conn == "disconnected"  # default
    sw.ap_states.clear()

    await ctx.disconnect()
    await ctx.disconnect()

    assert sw.ap_states == []


@pytest.mark.asyncio
async def test_disconnect_without_switch_does_not_explode(monkeypatch):
    """No Switch attached -> ap_conn still mutates but no send_ap_state."""
    ctx, state, _sw = _make_ctx(switch_connected=False)
    ctx.switch = None
    monkeypatch.setattr(
        CommonContext,
        "disconnect",
        lambda self, allow_autoreconnect=False: _record_bool([], allow_autoreconnect),
    )
    state.set_ap_conn("ready")

    await ctx.disconnect()

    assert state.ap_conn == "disconnected"


# ---- last-server prefill --------------------------------------------------
#
# CommonClient persists `last_server_address` to ~/.archipelago/
# _persistent_storage.yaml on every successful Connected, and
# CommonContext.suggested_address falls back to it when ctx.server_address
# is empty. SMOClient used to shadow that fallback by always passing
# `archipelago.gg:38281` (the old ApConfig default) into SMOContext at
# launch; with the default cleared, fresh-launch ctx.server_address is
# empty and the fallback kicks in. These tests pin that behavior.


@pytest.mark.asyncio
async def test_suggested_address_falls_back_to_persistent_store(monkeypatch):
    import Utils  # type: ignore[import-not-found]
    monkeypatch.setattr(
        Utils,
        "persistent_load",
        lambda: {"client": {"last_server_address": "example.com:1234"}},
    )

    ctx, _state, _sw = _make_ctx(switch_connected=False)
    assert ctx.server_address in ("", None)
    assert ctx.suggested_address == "example.com:1234"


@pytest.mark.asyncio
async def test_suggested_address_prefers_explicit_server_address(monkeypatch):
    import Utils  # type: ignore[import-not-found]
    monkeypatch.setattr(
        Utils,
        "persistent_load",
        lambda: {"client": {"last_server_address": "stored.example.com:1234"}},
    )

    ctx, _state, _sw = _make_ctx(switch_connected=False)
    ctx.server_address = "explicit.host:5678"
    assert ctx.suggested_address == "explicit.host:5678"
