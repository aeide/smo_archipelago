"""Tests for the Switch -> Bridge state-snapshot reconciliation path (M4.5).

The Switch sends a snapshot of every owned shine + capture on every (re)connect
right after HELLO. The bridge dispatches each snapshot entry through the same
`check` path live moon-get hooks use, so AP learns about anything the Switch
collected during a disconnect window.

Snapshot wire shape mirrors M4's `check` semantics: RAW SMO identifiers
(stage_name + object_id + shine_uid for moons; hack_name for captures). The
bridge resolves them downstream via shine_map.json / capture_map.json.

`BridgeState.add_checked_location` dedupes on the full ItemRef identity, so
re-sending the same snapshot is a no-op.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from client import protocol
from client.protocol import (
    HelloMsg,
    ItemKind,
    ItemRef,
    StateBeginMsg,
    StateChunkMsg,
    StateEndMsg,
)
from client.state import BridgeState, CheckEvent
from client.switch_server import SwitchServer


# ----- Direct unit tests on BridgeState's snapshot accumulator -----

def test_snapshot_accumulator_collects_raw_entries():
    s = BridgeState()
    s.begin_snapshot(save_slot=0)
    s.add_snapshot_chunk_shines("CapWorldHomeStage", [
        {"object_id": "MoonOurFirst", "shine_uid": 100},
        {"object_id": "MoonHatTrampoline", "shine_uid": 101},
    ])
    s.add_snapshot_chunk_shines("WaterfallWorldHomeStage", [
        {"object_id": "MoonMultiMoon", "shine_uid": 200},
    ])
    s.add_snapshot_chunk_meta(captures=["Kuribo", "Frog"], goal_reached=False)

    entries, goal = s.end_snapshot()
    assert goal is False
    assert len(entries) == 5
    moons = [e for e in entries if e["kind"] == "moon"]
    captures = [e for e in entries if e["kind"] == "capture"]
    assert len(moons) == 3
    assert len(captures) == 2
    assert moons[0]["stage_name"] == "CapWorldHomeStage"
    assert moons[0]["object_id"] == "MoonOurFirst"
    assert moons[0]["shine_uid"] == 100
    assert {c["hack_name"] for c in captures} == {"Kuribo", "Frog"}


def test_snapshot_accumulator_carries_goal_flag():
    s = BridgeState()
    s.begin_snapshot(save_slot=0)
    s.add_snapshot_chunk_meta(captures=None, goal_reached=True)
    _, goal = s.end_snapshot()
    assert goal is True


def test_snapshot_chunks_dropped_when_no_active_snapshot():
    s = BridgeState()
    # No begin_snapshot called.
    s.add_snapshot_chunk_shines("CapWorldHomeStage", [
        {"object_id": "MoonOurFirst", "shine_uid": 100},
    ])
    s.add_snapshot_chunk_meta(captures=["Frog"], goal_reached=False)
    entries, goal = s.end_snapshot()
    assert entries == []
    assert goal is False


def test_begin_resets_in_flight_snapshot():
    s = BridgeState()
    s.begin_snapshot(save_slot=0)
    s.add_snapshot_chunk_shines("CapWorldHomeStage", [
        {"object_id": "A", "shine_uid": 1},
    ])
    # New snapshot starts before end_snapshot — resets buffer.
    s.begin_snapshot(save_slot=1)
    s.add_snapshot_chunk_shines("WaterfallWorldHomeStage", [
        {"object_id": "B", "shine_uid": 2},
    ])
    entries, _ = s.end_snapshot()
    assert len(entries) == 1
    assert entries[0]["object_id"] == "B"
    assert s.last_snapshot_save_slot == 1


# ----- add_checked_location dedup behavior -----

def test_add_checked_location_dedupes_on_canonical_fields():
    s = BridgeState()
    e1 = CheckEvent(item=ItemRef(
        kind=ItemKind.MOON.value, kingdom="Cap", shine_id="Our First Power Moon"
    ))
    e2 = CheckEvent(item=ItemRef(
        kind=ItemKind.MOON.value, kingdom="Cap", shine_id="Our First Power Moon"
    ))
    assert s.add_checked_location(e1) is True
    assert s.add_checked_location(e2) is False
    assert len(s.checked_locations) == 1
    assert s.moons_checked_by_kingdom == {"Cap": 1}


def test_add_checked_location_dedupes_on_raw_fields():
    s = BridgeState()
    # Two raw-ID checks with the same stage+object identity.
    e1 = CheckEvent(item=ItemRef(
        kind=ItemKind.MOON.value,
        stage_name="CapWorldHomeStage", object_id="MoonOurFirst", shine_uid=100,
    ))
    e2 = CheckEvent(item=ItemRef(
        kind=ItemKind.MOON.value,
        stage_name="CapWorldHomeStage", object_id="MoonOurFirst", shine_uid=100,
    ))
    assert s.add_checked_location(e1) is True
    assert s.add_checked_location(e2) is False
    assert len(s.checked_locations) == 1


# ----- Integration: snapshot end-to-end through TCP -----

@pytest.mark.asyncio
async def test_snapshot_end_to_end_dispatches_synthetic_checks():
    state = BridgeState()
    forwarded_checks: list[dict] = []

    async def on_check(msg: dict) -> None:
        forwarded_checks.append(msg)

    async def on_goal() -> None:
        pass

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        # Drain HELLO replies (hello_ack + checked_replay + ap_state).
        await _drain_messages(reader, n=3, timeout=2.0)

        # Send a snapshot: 2 moons in one stage, 1 in another, plus a capture.
        # Captures are dropped by the snapshot dispatch (dict-derived signal
        # can't tell manual captures from grant-induced dict entries), so the
        # capture in _meta gets logged + ignored. Only moons reach AP.
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=[
                {"object_id": "MoonOurFirst", "shine_uid": 100},
                {"object_id": "MoonHatTrampoline", "shine_uid": 101},
            ]),
            StateChunkMsg(stage_name="WaterfallWorldHomeStage", shines=[
                {"object_id": "MoonMultiMoon", "shine_uid": 200},
            ]),
            StateChunkMsg(stage_name="_meta", captures=["Kuribo"], goal_reached=False),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        # 3 synthetic checks (moons only); the snapshot's capture entry was
        # dropped per the no-manual-capture-signal rule.
        assert len(forwarded_checks) == 3
        moons = [c for c in forwarded_checks if c["kind"] == "moon"]
        captures = [c for c in forwarded_checks if c["kind"] == "capture"]
        assert len(moons) == 3
        assert captures == []
        # Moons carry raw IDs (Switch never sent canonical here).
        moon_objs = sorted(m["object_id"] for m in moons)
        assert moon_objs == ["MoonHatTrampoline", "MoonMultiMoon", "MoonOurFirst"]
        # First moon shows correct stage.
        first_moon = next(m for m in moons if m["object_id"] == "MoonOurFirst")
        assert first_moon["stage_name"] == "CapWorldHomeStage"
        assert first_moon["shine_uid"] == 100

        # checked_locations was populated via dedup-aware add (3 entries).
        assert len(state.checked_locations) == 3
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_capture_dispatch_does_not_send_cappy_msg():
    """Snapshot-derived captures must NOT send the new CappyMsg path from
    _dispatch_check. The M6-phase-C reconcile-Cappy machinery
    (try_fire_reconcile_cappy) handles snapshot-derived bubbles by
    synthesizing an ItemMsg(from="(offline)") that the Switch formats
    locally. Both paths firing for the same loc_id would pop the same
    "Got Cascade Power Moon!" bubble twice for the same offline catch-up.

    Live capture-checks (post-Switch HELLO, not via snapshot) MUST keep
    firing CappyMsg — that's the capturesanity announcement. This test
    only locks down the snapshot-path suppression.
    """
    state = BridgeState()

    async def on_check(msg: dict) -> int | None:
        return 9001 if msg.get("hack_name") == "Killer" else None

    async def on_goal() -> None:
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        compose_moon_label=lambda loc_id: "Got Cascade Power Moon!",
        get_already_checked_loc_ids=lambda: set(),  # treat as fresh
    )
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await writer.drain()
        await _drain_messages(reader, n=3, timeout=2.0)

        # Snapshot with one capture entry that compose_label would label
        # as "Got Cascade Power Moon!" (this capture's location yields a
        # Moon item in this seed).
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="_meta", captures=["Killer"], goal_reached=False),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        # Send a ping so the reader has something to wake on regardless.
        writer.write(protocol.encode(protocol.PingMsg(ts_ms=1)))
        await writer.drain()

        # Drain whatever the bridge sent back. A CappyMsg slipping through
        # would arrive BEFORE the pong (Nagle-batched same TCP push), so
        # if the very first reply is the pong, no CappyMsg fired.
        msgs = await _drain_messages(reader, n=1, timeout=2.0)
        assert msgs[0]["t"] == "pong", (
            f"snapshot dispatch leaked a CappyMsg: {msgs[0]}"
        )

        # Sanity: live capture-check (NOT via snapshot) still fires
        # CappyMsg via the same code path.
        writer.write(protocol.encode(protocol.CheckMsg(
            kind=ItemKind.CAPTURE.value, hack_name="Killer",
        )))
        await writer.drain()
        msgs = await _drain_messages(reader, n=1, timeout=2.0)
        # Live capture's loc_id is also 9001 (was_new check uses the
        # get_already_checked callback above which returns empty), so it
        # was_new=True and the CappyMsg should fire.
        assert msgs[0] == {"t": "cappy", "text": "Got Cascade Power Moon!"}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_drops_all_capture_entries():
    """Snapshot path must NEVER fire capture-checks. SMO's hack dictionary
    is populated by being ALLOWED to use a capture — every AP grant, every
    baseline pre-populate, every prior-session /grant REPL command, every
    save-file edit lands an entry. A snapshot rebuilt from the dict
    therefore can't distinguish "manually captured this run" from "added
    by external means," and crediting from the dict has burned users
    (2026-05-18: granting T-Rex on a save with 6 leftover dict entries
    fired 6 phantom AP check-credits). Live CaptureStartHook is the only
    authoritative source — it fires reportCaptureChecked directly, not
    via snapshot."""
    state = BridgeState()
    forwarded_checks: list[dict] = []

    async def on_check(msg: dict) -> None:
        forwarded_checks.append(msg)

    async def on_goal() -> None:
        pass

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)

        # Three captures in the snapshot — none should reach the AP forwarder.
        # A moon in the same snapshot SHOULD still fire (moons are trustworthy).
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=[
                {"object_id": "MoonOurFirst", "shine_uid": 100},
            ]),
            StateChunkMsg(
                stage_name="_meta",
                captures=["Statue", "Killer", "Bubble"],
                goal_reached=False,
            ),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        captures = [c for c in forwarded_checks if c["kind"] == "capture"]
        moons = [c for c in forwarded_checks if c["kind"] == "moon"]
        assert captures == [], (
            f"expected zero capture forwards; got {captures}"
        )
        assert len(moons) == 1, f"moon snapshot path must still fire: {moons}"
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_replay_is_idempotent():
    """Sending the same snapshot twice produces zero forwarded checks the second time."""
    state = BridgeState()
    forwarded_checks: list[dict] = []

    async def on_check(msg: dict) -> None:
        forwarded_checks.append(msg)

    async def on_goal() -> None:
        pass

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)

        snapshot_msgs = [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=[
                {"object_id": "MoonA", "shine_uid": 1},
                {"object_id": "MoonB", "shine_uid": 2},
            ]),
            StateEndMsg(),
        ]

        # First snapshot: 2 forwarded.
        for m in snapshot_msgs:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)
        assert len(forwarded_checks) == 2

        # Second snapshot, identical content. on_check still fires (we always
        # forward through the same path), but BridgeState.add_checked_location
        # dedupes so checked_locations doesn't grow.
        before_dispatch = len(forwarded_checks)
        for m in snapshot_msgs:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)
        assert len(forwarded_checks) == before_dispatch + 2  # forwarded again
        assert len(state.checked_locations) == 2  # but state stays at 2
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_with_goal_flag_calls_on_goal():
    state = BridgeState()
    goal_calls: list[None] = []

    async def on_check(msg: dict) -> None:
        pass

    async def on_goal() -> None:
        goal_calls.append(None)

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)

        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="_meta", captures=None, goal_reached=True),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)
        assert len(goal_calls) == 1
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


# ----- ItemRef.to_replay_dict strips raw fields (M4 C++ parser is strict) -----

def test_item_ref_to_replay_dict_strips_raw_fields():
    """The C++ parseItemRefBody rejects unknown keys, so we must NOT send
    raw M4 fields (stage_name etc.) inside CheckedReplayMsg."""
    ref = ItemRef(
        kind=ItemKind.MOON.value,
        kingdom="Cap", shine_id="Our First Power Moon",
        stage_name="CapWorldHomeStage", object_id="MoonOurFirst", shine_uid=100,
    )
    d = ref.to_replay_dict()
    assert "stage_name" not in d
    assert "object_id" not in d
    assert "shine_uid" not in d
    assert "hack_name" not in d
    assert d["kingdom"] == "Cap"
    assert d["shine_id"] == "Our First Power Moon"


def test_checked_replay_msg_to_wire_uses_replay_dict():
    msg = protocol.CheckedReplayMsg(ids=[
        ItemRef(
            kind=ItemKind.MOON.value, kingdom="Cap", shine_id="Foo",
            stage_name="CapWorldHomeStage", object_id="MoonFoo",
        ),
    ])
    wire = msg.to_wire()
    assert wire["t"] == "checked_replay"
    assert len(wire["ids"]) == 1
    assert "stage_name" not in wire["ids"][0]


# ----- helpers -----

# ----- M6 phase C reconcile: deferred dispatch when AP not yet ready -----

@pytest.mark.asyncio
async def test_snapshot_buffers_when_ap_not_ready_then_drains():
    """Snapshot landing during the AP-handshake window must be buffered, not
    dispatched. This is the exact race we hit live: the Switch's HELLO arrived
    ~1.4s before AP's `Connected` packet, and every synthetic check dropped
    with "no AP id for location" because dp.location_name_to_id was empty."""
    state = BridgeState()
    forwarded: list[dict] = []
    ready = [False]  # mutable so we can flip mid-test

    async def on_check(msg: dict) -> int | None:
        forwarded.append(msg)
        return None

    async def on_goal() -> None:
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: ready[0],
    )
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)

        # AP still handshaking. Send snapshot.
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="WaterfallWorldHomeStage", shines=[
                {"object_id": "obj124", "shine_uid": 100},
            ]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)

        # Snapshot was buffered, NOT dispatched yet.
        assert forwarded == []
        assert sw._pending_snapshot_entries is not None
        assert len(sw._pending_snapshot_entries) == 1

        # AP comes ready; SMOContext._handle_ap_package(cmd="Connected")
        # calls drain_pending_snapshot.
        ready[0] = True
        await sw.drain_pending_snapshot()

        # Now the buffered entry is forwarded.
        assert len(forwarded) == 1
        assert forwarded[0]["stage_name"] == "WaterfallWorldHomeStage"
        assert forwarded[0]["object_id"] == "obj124"
        # Buffer was emptied — second drain is a no-op.
        assert sw._pending_snapshot_entries is None
        await sw.drain_pending_snapshot()
        assert len(forwarded) == 1  # unchanged
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_dispatches_immediately_when_ap_already_ready():
    """If the Switch reconnects while AP is already live (the normal case
    once the session is established), no buffering should happen — the
    snapshot must dispatch as it always did pre-M6-phase-C."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg: dict) -> int | None:
        forwarded.append(msg)
        return None

    async def on_goal() -> None:
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: True,  # AP already up
    )
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)

        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=[
                {"object_id": "MoonA", "shine_uid": 1},
            ]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)

        # Forwarded immediately, no buffering.
        assert len(forwarded) == 1
        assert sw._pending_snapshot_entries is None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_snapshot_back_compat_no_is_ap_ready_callback():
    """Wiring without `is_ap_ready` (legacy/test contexts) must keep the
    pre-M6-phase-C behavior: dispatch immediately, no buffer. Important so
    every existing test in this file (constructed without the new kwarg)
    still exercises the synchronous path."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg: dict) -> int | None:
        forwarded.append(msg)
        return None

    async def on_goal() -> None:
        pass

    # No is_ap_ready kwarg.
    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)

        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="X", shines=[{"object_id": "o", "shine_uid": 1}]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)

        assert len(forwarded) == 1
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


# ----- M6 phase C reconcile: live `check` messages also buffered -----

@pytest.mark.asyncio
async def test_live_check_buffers_when_ap_not_ready_then_drains():
    """The Switch's outbound check ring drains queued offline collects on
    every reconnect — a moon collected during the previous session that
    couldn't reach the bridge gets re-sent as a `check` message the moment
    the TCP socket is up. That race-loses to AP connect identically to
    the snapshot: bridge dispatches before dp is hot → "no AP id" drop.
    Both buffers drain together on `Connected`."""
    from client.protocol import CheckMsg
    state = BridgeState()
    forwarded: list[dict] = []
    ready = [False]

    async def on_check(msg: dict) -> int | None:
        forwarded.append(msg)
        return 1234  # fake loc_id resolved

    async def on_goal() -> None:
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: ready[0],
    )
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)

        # Switch's pump drains a previously-queued offline collect as a
        # CheckMsg the moment the socket is up. AP isn't ready yet.
        writer.write(protocol.encode(CheckMsg(
            kind="moon", stage_name="WaterfallWorldHomeStage",
            object_id="obj124", shine_uid=0,
        )))
        await writer.drain()
        await asyncio.sleep(0.1)

        # Live check was buffered, not dispatched.
        assert forwarded == []
        assert len(sw._pending_live_checks) == 1

        # AP comes ready → drain.
        ready[0] = True
        await sw.drain_pending_snapshot()

        # Live check forwarded.
        assert len(forwarded) == 1
        assert forwarded[0]["stage_name"] == "WaterfallWorldHomeStage"
        assert forwarded[0]["object_id"] == "obj124"
        assert sw._pending_live_checks == []
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_live_check_dispatches_immediately_when_ap_ready():
    """Confirm the live-check fast path is unchanged when AP is up."""
    from client.protocol import CheckMsg
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg: dict) -> int | None:
        forwarded.append(msg)
        return None

    async def on_goal() -> None:
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: True,
    )
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)
        writer.write(protocol.encode(CheckMsg(
            kind="moon", stage_name="X", object_id="o", shine_uid=1,
        )))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert len(forwarded) == 1
        assert sw._pending_live_checks == []
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


# ----- M6 phase C reconcile: Cappy bubble synthesis -----

@pytest.mark.asyncio
async def test_reconcile_fires_cappy_for_self_moon():
    """End-to-end: deferred dispatch + try_fire_reconcile_cappy. Snapshot
    arrives pre-AP-ready, drain fires after, scout is available, builder
    returns a self-routed moon ItemMsg → SwitchServer enqueues it via
    `send_item`, which surfaces as a Cappy bubble on the Switch."""
    state = BridgeState()
    ready = [False]
    items_sent: list[Any] = []  # ItemMsg objects

    async def on_check(msg: dict) -> int | None:
        # Pretend report_check resolved this entry to loc_id=4242.
        return 4242

    async def on_goal() -> None:
        pass

    # Builder mimics SMOContext.build_reconcile_cappy_item — keyed on loc_id.
    scouts_ready = [False]
    def builder(loc_id: int):
        if not scouts_ready[0]:
            return None  # scout not yet absorbed
        from client.protocol import ItemMsg
        return ItemMsg(
            kind="moon", kingdom="Cascade", shine_id="Behind the Waterfall",
            name="Cascade Power Moon", from_="(offline)",
        )

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: ready[0],
        build_reconcile_cappy_item=builder,
    )
    # Capture send_item calls without standing up a TCP server.
    async def fake_send_item(item):
        items_sent.append(item)
    sw.send_item = fake_send_item  # type: ignore[assignment]

    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)

        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="WaterfallWorldHomeStage", shines=[
                {"object_id": "obj124", "shine_uid": 100},
            ]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)

        # AP comes ready; drain.
        ready[0] = True
        await sw.drain_pending_snapshot()

        # Scouts not loaded yet → Cappy still pending.
        assert items_sent == []
        assert 4242 in sw._reconcile_cappy_pending

        # Scouts land via LocationInfo absorption (SMOContext calls
        # try_fire_reconcile_cappy after each absorb).
        scouts_ready[0] = True
        await sw.try_fire_reconcile_cappy()

        assert len(items_sent) == 1
        msg = items_sent[0]
        assert msg.kind == "moon"
        assert msg.kingdom == "Cascade"
        assert msg.name == "Cascade Power Moon"
        assert msg.from_ == "(offline)"  # sentinel — passes self-suppress filter
        # Set cleared after fire.
        assert sw._reconcile_cappy_pending == set()

        # Idempotent — second fire is a no-op.
        await sw.try_fire_reconcile_cappy()
        assert len(items_sent) == 1
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reconcile_suppresses_cappy_on_burst_threshold():
    """Fresh-AP-slot guard: when a single drain produces >5 freshly-checked
    entries, suppress the WHOLE drain's Cappy bubbles. Bridge has still
    forwarded each LocationCheck to AP — only the per-item bubble is
    skipped. Matches the user's 12:48 log scenario: a long binge of
    offline moon collects would otherwise flood the CappyMessenger ring."""
    from client.switch_server import RECONCILE_CAPPY_BURST_THRESHOLD
    state = BridgeState()
    items_sent: list[Any] = []
    # Each moon resolves to a distinct loc_id so all count as "fresh".
    next_id = [10_000]
    async def on_check(msg: dict) -> int | None:
        next_id[0] += 1
        return next_id[0]
    async def on_goal() -> None:
        pass
    def builder(loc_id: int):
        from client.protocol import ItemMsg
        return ItemMsg(kind="moon", kingdom="Cascade", shine_id="Power Moon",
                       from_="(offline)")
    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: False,
        build_reconcile_cappy_item=builder,
    )
    async def fake_send_item(item):
        items_sent.append(item)
    sw.send_item = fake_send_item  # type: ignore[assignment]
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)
        burst = RECONCILE_CAPPY_BURST_THRESHOLD + 3  # >threshold
        shines = [{"object_id": f"obj{i}", "shine_uid": 5000 + i}
                  for i in range(burst)]
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=shines),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)
        await sw.drain_pending_snapshot()
        # All `burst` checks dispatched to AP (per on_check call count).
        assert next_id[0] - 10_000 == burst
        # But no Cappy bubbles fired — burst threshold tripped.
        assert items_sent == []
        assert sw._reconcile_cappy_pending == set()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reconcile_fires_cappy_at_burst_boundary():
    """Exactly at the threshold (5 in current config), bubbles still fire.
    Locks the >-vs->= boundary so a refactor doesn't silently change it."""
    from client.switch_server import RECONCILE_CAPPY_BURST_THRESHOLD
    state = BridgeState()
    items_sent: list[Any] = []
    next_id = [20_000]
    async def on_check(msg: dict) -> int | None:
        next_id[0] += 1
        return next_id[0]
    async def on_goal() -> None:
        pass
    def builder(loc_id: int):
        from client.protocol import ItemMsg
        return ItemMsg(kind="moon", kingdom="Cascade", shine_id="Power Moon",
                       from_="(offline)")
    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: False,
        build_reconcile_cappy_item=builder,
    )
    async def fake_send_item(item):
        items_sent.append(item)
    sw.send_item = fake_send_item  # type: ignore[assignment]
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)
        at_threshold = [{"object_id": f"obj{i}", "shine_uid": 7000 + i}
                        for i in range(RECONCILE_CAPPY_BURST_THRESHOLD)]
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="CapWorldHomeStage", shines=at_threshold),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)
        await sw.drain_pending_snapshot()
        # All exactly-threshold entries fire Cappy.
        assert len(items_sent) == RECONCILE_CAPPY_BURST_THRESHOLD
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reconcile_does_not_fire_cappy_for_other_player_moon():
    """Builder returning None for non-self items — those go through AP's
    PrintMsg path, the bridge shouldn't double-announce them."""
    state = BridgeState()
    items_sent: list[Any] = []

    async def on_check(msg: dict) -> int | None:
        return 7777

    async def on_goal() -> None:
        pass

    # Builder always returns None (simulates "scout says recipient != self").
    def builder(loc_id: int):
        return None

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: False,
        build_reconcile_cappy_item=builder,
    )
    async def fake_send_item(item):
        items_sent.append(item)
    sw.send_item = fake_send_item  # type: ignore[assignment]

    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="X", shines=[{"object_id": "o", "shine_uid": 1}]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)
        await sw.drain_pending_snapshot()
        # Multiple retries still produce no Cappy bubble (builder always None).
        await sw.try_fire_reconcile_cappy()
        await sw.try_fire_reconcile_cappy()
        assert items_sent == []
        # But the loc_id stays pending — a future scout absorption could
        # still resolve. (Test harness never flips builder, so it stays.)
        assert 7777 in sw._reconcile_cappy_pending
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reconcile_skips_cappy_for_already_checked_locations():
    """The user's request: "if it wasn't there already". An entry whose
    loc_id was ALREADY in locations_checked before drain shouldn't fire
    Cappy — it's a re-replay, not a new offline collect."""
    state = BridgeState()

    async def on_check(msg: dict) -> int | None:
        # report_check resolves the snapshot entry to loc_id=4242, which
        # the get_already_checked snapshot already contains.
        return 4242

    async def on_goal() -> None:
        pass

    builder_called: list[int] = []
    def builder(loc_id: int):
        builder_called.append(loc_id)
        from client.protocol import ItemMsg
        return ItemMsg(kind="moon", name="X", from_="(offline)")

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        is_ap_ready=lambda: False,
        build_reconcile_cappy_item=builder,
        # The callback returns the pre-drain snapshot of checked loc_ids.
        # 4242 is already known → drain should skip Cappy for it.
        get_already_checked_loc_ids=lambda: {4242},
    )
    items_sent: list[Any] = []
    async def fake_send_item(item):
        items_sent.append(item)
    sw.send_item = fake_send_item  # type: ignore[assignment]

    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg()))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="W", shines=[{"object_id": "obj124", "shine_uid": 100}]),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.1)
        await sw.drain_pending_snapshot()
        # Builder never called — loc_id 4242 was already in the pre-drain
        # snapshot, so it wasn't queued for reconcile-Cappy.
        assert builder_called == []
        assert items_sent == []
        assert sw._reconcile_cappy_pending == set()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


# ----- helpers -----

async def _drain_messages(reader: asyncio.StreamReader, n: int, timeout: float) -> list[dict]:
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
