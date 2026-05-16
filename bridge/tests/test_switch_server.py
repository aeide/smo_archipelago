"""End-to-end test of SwitchServer using a real TCP loopback connection."""

from __future__ import annotations

import asyncio
import json

import pytest

from smo_ap_bridge import protocol
from smo_ap_bridge.protocol import HelloMsg, ItemMsg, ItemRef, ItemKind
from smo_ap_bridge.state import BridgeState, ItemEvent, CheckEvent
from smo_ap_bridge.switch_server import SwitchServer


@pytest.mark.asyncio
async def test_hello_handshake_and_replay():
    state = BridgeState()
    state.slot = "Mario"
    state.seed = "TEST"
    # Pre-populate state so the HELLO replay sends something interesting.
    state.add_received_item(ItemEvent(
        item=ItemRef(kind=ItemKind.CAPTURE.value, cap="Frog"), sender="Bob"
    ))
    state.add_checked_location(CheckEvent(
        item=ItemRef(kind=ItemKind.MOON.value, kingdom="Cascade", shine_id="DinoNest")
    ))

    checks_received: list[dict] = []
    goals_received: list[None] = []

    async def on_check(msg: dict) -> None:
        checks_received.append(msg)

    async def on_goal() -> None:
        goals_received.append(None)

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server  # plug in so stop() works
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # Send HELLO.
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0",
                                              cap_table_hash="sha1:cafebabe")))
        await writer.drain()

        # Expect: hello_ack, then checked_replay, then 1 item, then ap_state.
        msgs = await _drain_messages(reader, n=4, timeout=2.0)
        kinds = [m["t"] for m in msgs]
        assert kinds == ["hello_ack", "checked_replay", "item", "ap_state"]
        assert msgs[0]["seed"] == "TEST"
        assert msgs[0]["slot"] == "Mario"
        # SwitchServer constructed without deathlink_enabled -> defaults False.
        assert msgs[0]["deathlink_enabled"] is False
        assert len(msgs[1]["ids"]) == 1
        assert msgs[1]["ids"][0]["shine_id"] == "DinoNest"
        assert msgs[2]["cap"] == "Frog"
        assert msgs[2]["from"] == "Bob"

        # Send a check; verify on_check fires and bridge state updates.
        writer.write(protocol.encode(protocol.CheckMsg(
            kind=ItemKind.MOON.value, kingdom="Sand", shine_id="PoolUnderwater"
        )))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert len(checks_received) == 1
        assert checks_received[0]["kingdom"] == "Sand"
        assert state.moons_checked_by_kingdom.get("Sand") == 1

        # Send a raw-ID moon check (M4 wire-format additions).
        writer.write(protocol.encode(protocol.CheckMsg(
            kind=ItemKind.MOON.value,
            stage_name="CapWorldHomeStage",
            object_id="MoonOurFirst",
            shine_uid=12,
        )))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert len(checks_received) == 2
        assert checks_received[1]["stage_name"] == "CapWorldHomeStage"
        assert checks_received[1]["object_id"] == "MoonOurFirst"
        assert checks_received[1]["shine_uid"] == 12

        # Send a capture-by-hack_name check.
        writer.write(protocol.encode(protocol.CheckMsg(
            kind=ItemKind.CAPTURE.value, hack_name="Goomba"
        )))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert checks_received[2]["hack_name"] == "Goomba"

        # Send goal; verify on_goal fires.
        writer.write(protocol.encode(protocol.GoalMsg()))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert goals_received == [None]

        # Ping/pong.
        writer.write(protocol.encode(protocol.PingMsg(ts_ms=99)))
        await writer.drain()
        pong = (await _drain_messages(reader, n=1, timeout=1.0))[0]
        assert pong == {"t": "pong", "ts_ms": 99}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_death_message_dispatches_to_handler():
    state = BridgeState()

    deaths_received: list[int] = []

    async def on_check(_): ...
    async def on_goal(): ...
    async def on_death(ts_ms: int) -> None:
        deaths_received.append(ts_ms)

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal, on_death=on_death)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await writer.drain()
        await _drain_messages(reader, n=3, timeout=2.0)

        writer.write(protocol.encode(protocol.DeathMsg(ts_ms=42_000)))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert deaths_received == [42_000]
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_hello_ack_advertises_deathlink_enabled():
    """When bridge config has DeathLink on, hello_ack must tell the mod so it
    will act on inbound kill messages. (Outbound is bridge-gated separately,
    so this flag exists purely for the inbound apply path.)"""
    state = BridgeState()

    async def on_check(_): ...
    async def on_goal(): ...

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal, deathlink_enabled=True)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await writer.drain()
        msgs = await _drain_messages(reader, n=3, timeout=2.0)
        assert msgs[0]["t"] == "hello_ack"
        assert msgs[0]["deathlink_enabled"] is True
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_unknown_message_yields_err():
    state = BridgeState()

    async def on_check(_): ...
    async def on_goal(): ...

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b'{"t":"hello"}\n{"t":"bogus_type"}\n')
        await writer.drain()
        msgs = await _drain_messages(reader, n=4, timeout=2.0)
        # hello_ack + checked_replay (empty) + ap_state + err
        kinds = [m["t"] for m in msgs]
        assert "err" in kinds
        err = next(m for m in msgs if m["t"] == "err")
        assert err["code"] == "unknown_kind"
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_second_connection_rejected_busy():
    state = BridgeState()

    async def on_check(_): ...
    async def on_goal(): ...

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    r1, w1 = await asyncio.open_connection("127.0.0.1", port)
    try:
        w1.write(protocol.encode(HelloMsg()))
        await w1.drain()
        await _drain_messages(r1, n=3, timeout=2.0)  # consume hello_ack/replay/ap_state

        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        try:
            msgs = await _drain_messages(r2, n=1, timeout=2.0)
            assert msgs[0]["t"] == "err"
            assert msgs[0]["code"] == "busy"
        finally:
            w2.close()
            try:
                await w2.wait_closed()
            except Exception:
                pass
    finally:
        w1.close()
        try:
            await w1.wait_closed()
        except Exception:
            pass
        await sw.stop()


async def _drain_messages(reader: asyncio.StreamReader, n: int, timeout: float) -> list[dict]:
    """Read until we've parsed n full JSON lines or timeout expires."""
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
