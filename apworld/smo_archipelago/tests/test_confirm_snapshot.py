"""Tests for the bridge-side /confirm_snapshot gate.

User report 2026-05-23: an existing 8-moon save auto-loaded after a Switch
reboot, and the snapshot path credited 3 moons to AP before the user could
click "New Game". LocationChecks are persisted server-side; once sent the
user must /forfeit to unwind. The Switch-side `save_was_loaded &&
CappyMessenger::hasDispatchedSinceReset()` gate proves only that Mario is
in a live gameplay scene with save data resident — NOT that the player
picked this save for this AP run.

The bridge-side gate intercepts state_end (and the AP-not-ready drain)
between BridgeState.end_snapshot() and report_check forwarding. When the
snapshot would credit at least one NEW AP location (or report a fresh
`goal_reached` that hasn't been shipped), the entries are stashed on a
held slot and the user is prompted to /confirm_snapshot or /reject_snapshot.

Tests cover:
  * the pure classifier function (auto-confirm vs hold semantics)
  * the end-to-end TCP path (state_end with new entries -> no checks
    forwarded until /confirm_snapshot)
  * the back-compat case (legacy constructor without resolve_entry_to_loc_id
    auto-confirms, preserving pre-2026-05-23 behavior so existing tests
    keep passing)
  * replace-on-new (a second held snapshot supersedes the first)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from client import protocol
from client.protocol import (
    HelloMsg,
    ItemKind,
    StateBeginMsg,
    StateChunkMsg,
    StateEndMsg,
)
from client.state import BridgeState
from client.switch_server import (
    SwitchServer,
    _classify_snapshot_for_user_confirm,
)


# ---- Pure classifier unit tests ----------------------------------------


def _moon_entry(stage: str, object_id: str, shine_uid: int) -> dict:
    return {
        "kind": "moon",
        "stage_name": stage,
        "object_id": object_id,
        "shine_uid": shine_uid,
    }


def test_classifier_back_compat_when_resolver_unwired():
    """Legacy / test harnesses that construct SwitchServer without the
    resolve_entry_to_loc_id kwarg must keep the pre-2026-05-23 behavior:
    every snapshot auto-confirms. Otherwise every existing test that
    exercises the snapshot path would start hanging on a phantom
    /confirm_snapshot wait."""
    entries = [_moon_entry("CapWorldHomeStage", "MoonOurFirst", 100)]
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=entries,
        goal_reached=True,
        resolve_entry_to_loc_id=None,
        get_already_checked_loc_ids=None,
        is_goal_finished=None,
    )
    assert auto is True
    assert new_count == 0
    assert already_count == 0


def test_classifier_empty_snapshot_auto_confirms():
    """The New Game case: snapshot has no entries and no goal — there is
    literally nothing to gate. Holding here would force the user to
    /confirm_snapshot after every save-load even on the canonical happy
    path."""
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=[],
        goal_reached=False,
        resolve_entry_to_loc_id=lambda e: 99,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is True
    assert (new_count, already_count) == (0, 0)


def test_classifier_all_already_checked_auto_confirms():
    """Switch reconnect mid-session: snapshot enumerates everything the
    player has already collected. AP's locations_checked is populated;
    every entry dedupes against it. Nothing fresh -> auto-confirm."""
    entries = [
        _moon_entry("CapWorldHomeStage", "MoonOurFirst", 100),
        _moon_entry("CapWorldHomeStage", "MoonHatTrampoline", 101),
    ]
    already = {1001, 1002}
    resolver_table = {
        (100,): 1001,
        (101,): 1002,
    }
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=entries,
        goal_reached=False,
        resolve_entry_to_loc_id=lambda e: resolver_table[(e["shine_uid"],)],
        get_already_checked_loc_ids=lambda: already,
        is_goal_finished=lambda: False,
    )
    assert auto is True
    assert (new_count, already_count) == (0, 2)


def test_classifier_at_least_one_new_loc_holds():
    """The wrong-save case from the user report: a save with 3 moons was
    loaded but the AP slot has 0 locations checked. Every resolved entry
    is new -> hold for /confirm_snapshot."""
    entries = [
        _moon_entry("CapWorldHomeStage", "MoonOurFirst", 100),
        _moon_entry("CapWorldHomeStage", "MoonHatTrampoline", 101),
        _moon_entry("WaterfallWorldHomeStage", "MoonRockfall", 200),
    ]
    resolver_table = {
        (100,): 1001,
        (101,): 1002,
        (200,): 2001,
    }
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=entries,
        goal_reached=False,
        resolve_entry_to_loc_id=lambda e: resolver_table[(e["shine_uid"],)],
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is False
    assert (new_count, already_count) == (3, 0)


def test_classifier_captures_excluded_from_counts():
    """Snapshot-derived captures are dropped before forwarding (see
    `_dispatch_snapshot_entries`'s capture-drop). They MUST also be
    excluded from the gate's counts — otherwise a save with only the
    Frog hack auto-populated in the dictionary would hold a snapshot
    even though no LocationCheck would actually fire."""
    entries = [
        {"kind": "capture", "hack_name": "Frog"},
        {"kind": "capture", "hack_name": "Killer"},
    ]
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=entries,
        goal_reached=False,
        resolve_entry_to_loc_id=lambda e: 9999,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is True
    assert (new_count, already_count) == (0, 0)


def test_classifier_unresolved_entries_dropped():
    """Entries that can't map to an AP loc_id (unknown shine, missing
    canonical fields) don't count toward `new` — sending them through
    report_check would log a warning and return None, never reaching
    AP. The gate mirrors that semantically."""
    entries = [
        _moon_entry("UnknownStage", "UnknownObject", 9999),
        _moon_entry("CapWorldHomeStage", "MoonOurFirst", 100),
    ]
    def resolve(e):
        return 1001 if e["shine_uid"] == 100 else None
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=entries,
        goal_reached=False,
        resolve_entry_to_loc_id=resolve,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is False
    assert new_count == 1  # only the resolvable one


def test_classifier_fresh_goal_holds_even_when_no_entries():
    """An empty snapshot with goal_reached=True and goal_sent=False is
    rare but possible (Switch's ApState::goal_sent loaded from a save
    that's pre-credits but the player edited their progress, OR a
    crash-replay loop where the goal flag stuck on a non-victory save).
    Hold so the user reviews — auto-firing ClientGoal on every save load
    is the same persistence pitfall as forwarding LocationChecks."""
    auto, new_count, already_count = _classify_snapshot_for_user_confirm(
        entries=[],
        goal_reached=True,
        resolve_entry_to_loc_id=lambda e: 1,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is False
    assert (new_count, already_count) == (0, 0)


def test_classifier_redundant_goal_after_report_auto_confirms():
    """After report_goal has shipped ClientGoal this session, a subsequent
    snapshot reporting `goal_reached=True` is redundant — the server
    already accepted it. Auto-confirm so save-load loops don't pile up
    held snapshots."""
    auto, _, _ = _classify_snapshot_for_user_confirm(
        entries=[],
        goal_reached=True,
        resolve_entry_to_loc_id=lambda e: 1,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: True,  # already shipped
    )
    assert auto is True


def test_classifier_resolver_exception_treated_as_unresolved():
    """resolve_entry_to_loc_id is wired through SMOContext code that can
    raise on a malformed entry. Swallow the exception (logged) and treat
    that entry as unresolved — better than crashing the snapshot dispatch
    on a corrupt wire payload."""
    def explodes(e):
        raise RuntimeError("boom")
    auto, new_count, _ = _classify_snapshot_for_user_confirm(
        entries=[_moon_entry("CapWorldHomeStage", "MoonOurFirst", 100)],
        goal_reached=False,
        resolve_entry_to_loc_id=explodes,
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    assert auto is True
    assert new_count == 0


# ---- End-to-end TCP gate tests -----------------------------------------


async def _drain_messages(reader: asyncio.StreamReader, n: int, timeout: float):
    """Read up to `n` JSON messages from the Switch-side socket."""
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

    try:
        await asyncio.wait_for(_pump(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return out


async def _start_local_server(sw: SwitchServer):
    server = await asyncio.start_server(sw._handle_client, "127.0.0.1", 0)
    sw._server = server
    return server, server.sockets[0].getsockname()[1]


def _make_resolver(table: dict):
    """Build a resolver that maps (stage, object) -> loc_id."""
    def resolve(entry):
        key = (entry.get("stage_name"), entry.get("object_id"))
        return table.get(key)
    return resolve


def _wrong_save_snapshot_msgs() -> list:
    """Reproduce the 2026-05-23 wire payload: 3 moons in Cascade, no goal.
    Mirrors the SMOClient log line `snapshot end: 6 entries goal=False`
    after the capture-drop trims to 3 forwarded checks."""
    return [
        StateBeginMsg(mod_ver="0.1.0", save_slot=0),
        StateChunkMsg(stage_name="WaterfallWorldHomeStage", shines=[
            {"object_id": "MoonOurFirst", "shine_uid": 100},
            {"object_id": "MoonStoneChomp", "shine_uid": 101},
            {"object_id": "MoonTimerChallenge1", "shine_uid": 102},
        ]),
        StateChunkMsg(stage_name="_meta", captures=[], goal_reached=False),
        StateEndMsg(),
    ]


@pytest.mark.asyncio
async def test_state_end_with_new_locs_holds_until_confirm():
    """The user's 2026-05-23 scenario: fresh AP slot, wrong save loaded with
    3 moons already collected. With the gate wired, no LocationChecks
    reach AP — entries land on the held slot."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg):
        forwarded.append(msg)
        return {
            ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
            ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
            ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
        }.get((msg.get("stage_name"), msg.get("object_id")))

    async def on_goal():
        pass

    resolver = _make_resolver({
        ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
        ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
        ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
    })

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        resolve_entry_to_loc_id=resolver,
        get_already_checked_loc_ids=lambda: set(),  # fresh AP slot
        is_goal_finished=lambda: False,
    )
    server, port = await _start_local_server(sw)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in _wrong_save_snapshot_msgs():
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        # Gate held the snapshot. NO LocationChecks reached AP.
        assert forwarded == []

        summary = sw.held_snapshot_summary()
        assert summary is not None
        new_count, already_count, goal = summary
        assert new_count == 3
        assert already_count == 0
        assert goal is False

        # Operator confirms — entries now flow through report_check.
        released = await sw.confirm_pending_snapshot()
        assert released is True
        # 3 moons forward — captures stay dropped (none in this snapshot).
        assert len(forwarded) == 3
        assert sw.held_snapshot_summary() is None
        # Second confirm is a no-op (nothing held).
        released_again = await sw.confirm_pending_snapshot()
        assert released_again is False
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reject_drops_held_snapshot_without_forwarding():
    """Operator types /reject_snapshot after realizing the wrong save loaded.
    The held entries vanish — no LocationChecks ever reach AP."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg):
        forwarded.append(msg)
        return 1001

    async def on_goal():
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        resolve_entry_to_loc_id=_make_resolver({
            ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
            ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
            ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
        }),
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    server, port = await _start_local_server(sw)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in _wrong_save_snapshot_msgs():
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        assert sw.held_snapshot_summary() is not None
        assert sw.reject_pending_snapshot() is True
        assert sw.held_snapshot_summary() is None
        assert forwarded == []
        # Second reject is a no-op.
        assert sw.reject_pending_snapshot() is False
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_second_snapshot_replaces_held():
    """Operator realizes the wrong save loaded, backs out to the title
    screen, picks New Game. SMO sends a fresh state_end with 0 entries —
    that superseding snapshot must REPLACE the held wrong-save snapshot,
    not stack on top of it. After replacement the new (empty) snapshot
    auto-confirms because it's a no-op, so /confirm_snapshot has nothing
    to release. Last-write-wins."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg):
        forwarded.append(msg)
        return 1001

    async def on_goal():
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        resolve_entry_to_loc_id=_make_resolver({
            ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
            ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
            ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
        }),
        get_already_checked_loc_ids=lambda: set(),
        is_goal_finished=lambda: False,
    )
    server, port = await _start_local_server(sw)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)

        # First snapshot — held.
        for m in _wrong_save_snapshot_msgs():
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)
        assert sw.held_snapshot_summary() == (3, 0, False)

        # Second snapshot — empty (New Game). Auto-confirms, supersedes
        # the previous held one.
        for m in [
            StateBeginMsg(mod_ver="0.1.0", save_slot=0),
            StateChunkMsg(stage_name="_meta", captures=[], goal_reached=False),
            StateEndMsg(),
        ]:
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        assert sw.held_snapshot_summary() is None
        assert forwarded == []  # neither snapshot forwarded
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_back_compat_legacy_constructor_auto_confirms():
    """Existing tests in test_state_reconciliation.py construct SwitchServer
    without resolve_entry_to_loc_id. They must keep passing — every
    snapshot auto-confirms exactly as before the gate landed."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg):
        forwarded.append(msg)
        return None

    async def on_goal():
        pass

    sw = SwitchServer("127.0.0.1", 0, state, on_check, on_goal)  # no kwargs
    server, port = await _start_local_server(sw)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in _wrong_save_snapshot_msgs():
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        # Forwarded synchronously, no hold.
        assert len(forwarded) == 3
        assert sw.held_snapshot_summary() is None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()


@pytest.mark.asyncio
async def test_reconnect_mid_session_auto_confirms():
    """Switch Wi-Fi blip — same save, but the Switch reconnects and
    resends a snapshot for every moon already collected. AP already has
    all 3 in `locations_checked`. The gate sees zero new entries and
    auto-confirms — there is no UX cost to a reconnect."""
    state = BridgeState()
    forwarded: list[dict] = []

    async def on_check(msg):
        forwarded.append(msg)
        return {
            ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
            ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
            ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
        }.get((msg.get("stage_name"), msg.get("object_id")))

    async def on_goal():
        pass

    sw = SwitchServer(
        "127.0.0.1", 0, state, on_check, on_goal,
        resolve_entry_to_loc_id=_make_resolver({
            ("WaterfallWorldHomeStage", "MoonOurFirst"): 1001,
            ("WaterfallWorldHomeStage", "MoonStoneChomp"): 1002,
            ("WaterfallWorldHomeStage", "MoonTimerChallenge1"): 1003,
        }),
        get_already_checked_loc_ids=lambda: {1001, 1002, 1003},
        is_goal_finished=lambda: False,
    )
    server, port = await _start_local_server(sw)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(protocol.encode(HelloMsg(mod_ver="0.1.0", smo_ver="1.0.0")))
        await _drain_messages(reader, n=3, timeout=2.0)
        for m in _wrong_save_snapshot_msgs():
            writer.write(protocol.encode(m))
        await writer.drain()
        await asyncio.sleep(0.2)

        # All three already-checked — forwarded synchronously through
        # report_check. The bridge's downstream dedup (locations_checked)
        # is what stops AP from getting a redundant LocationChecks.
        # From the gate's perspective: auto-confirm, no hold.
        assert sw.held_snapshot_summary() is None
        assert len(forwarded) == 3
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        await sw.stop()
