"""Tests for SMOClientCommandProcessor — the `/`-command surface in
`context.py` — plus a regression test for the AP-server-issued ItemMsg
name-resolution path.

The pure parser is exercised in test_repl.py.

Gated on Archipelago availability (subclassing CommonContext requires
CommonClient on sys.path) — same pattern as test_deathlink.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Worktrees don't carry an initialized vendor/Archipelago submodule, so fall
# back to the main checkout one level above the worktree root (the same
# pattern test_connect_gate.py uses). Without this, every test in this file
# silently skips in a `git worktree`-based dev loop.
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

from client.context import SMOContext, SMOClientCommandProcessor  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.protocol import ItemMsg  # noqa: E402
from client.state import BridgeState  # noqa: E402

_APWORLD_DATA = Path(__file__).resolve().parent.parent / "data"


class _StubSwitch:
    def __init__(self) -> None:
        self.items: list[ItemMsg] = []
        self.kills: list = []
        self.labels: list = []
        self.outstanding: list = []
        self.ap_states: list[str] = []
        self.capturesanity_calls: list[bool] = []
        self.push_capturesanity_calls: int = 0
        self.deathlink_calls: list[bool] = []
        self.push_deathlink_calls: int = 0

    async def send_item(self, item: ItemMsg) -> None:
        self.items.append(item)

    async def send_kill(self, kill) -> None:
        self.kills.append(kill)

    async def send_moon_label(self, label) -> None:
        self.labels.append(label)

    async def send_outstanding(self, msg) -> None:
        # M6 phase D: context.py pushes the authoritative per-kingdom
        # balance to the Switch whenever a Moon item is granted (so
        # ap_moons_kingdom[bit] on the mod side stays in sync). Stub it
        # for tests that just observe send_item.
        self.outstanding.append(msg)

    async def send_ap_state(self, conn: str) -> None:
        self.ap_states.append(conn)

    def set_capturesanity_enabled(self, enabled: bool) -> None:
        self.capturesanity_calls.append(bool(enabled))

    async def push_capturesanity_replay(self) -> None:
        self.push_capturesanity_calls += 1

    def set_deathlink_enabled(self, enabled: bool) -> None:
        self.deathlink_calls.append(bool(enabled))

    async def push_deathlink_helloack(self) -> None:
        self.push_deathlink_calls += 1


@pytest.mark.asyncio
async def test_cmd_inject_deathlink_routes_killmsg_to_switch():
    import asyncio
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    proc = SMOClientCommandProcessor(ctx)
    proc._cmd_inject_deathlink("Tester", "for science")
    await asyncio.sleep(0)

    assert len(sw.kills) == 1
    assert sw.kills[0].source == "Tester"
    assert sw.kills[0].cause == "for science"


@pytest.mark.asyncio
async def test_ap_received_item_carries_name_for_moon():
    """Regression: AP-issued moons must reach the Switch with their name.

    The bug: `ClassifiedItem.to_ref()` used to zero `name` for non-OTHER
    kinds, so MOON/CAPTURE items arrived on the Switch with no
    `name` field (stripped by `_strip_none`) and rendered as `?` in-game.
    """
    import asyncio
    state = BridgeState()
    ctx = SMOContext(
        server_address=None, password=None,
        state=state,
        datapackage=DataPackage(apworld_data_dir=_APWORLD_DATA),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    # Pretend the AP DataPackage handshake completed.
    ctx.dp.item_id_to_name[42] = "Cascade Kingdom Power Moon"
    ctx.dp.item_name_to_id["Cascade Kingdom Power Moon"] = 42

    await ctx._handle_ap_package("ReceivedItems", {
        "items": [{"item": 42, "player": 0, "flags": 0}],
    })
    await asyncio.sleep(0)

    assert len(sw.items) == 1
    msg = sw.items[0]
    assert msg.kind == "moon"
    assert msg.kingdom == "Cascade"
    assert msg.shine_id == "Power Moon"
    assert msg.name == "Cascade Kingdom Power Moon"

    # Wire payload must include the name (not stripped as None).
    from client.protocol import encode
    wire = encode(msg).decode("utf-8")
    assert '"name":"Cascade Kingdom Power Moon"' in wire


@pytest.mark.asyncio
async def test_connected_handler_pushes_capturesanity_off_to_switch():
    """Regression: the Connected handler must extract `capturesanity`
    from the packet's slot_data dict (NOT from `self.slot_data`, which
    CommonContext does not auto-stash) and push it to the Switch.

    The original implementation hit an AttributeError mid-handler,
    which silently broke EVERY post-Connected side effect (scout warm,
    notify subscription, capturesanity push). Catching this here
    prevents a regression where a future change reintroduces
    `self.slot_data` or other CommonContext attributes that don't exist."""
    import asyncio
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    # Default before Connected: True (fail-safe = current behavior).
    assert ctx.capturesanity_enabled is True

    await ctx._handle_ap_package("Connected", {
        "slot_data": {"capturesanity": 0},
        # Other Connected fields the handler tolerates being absent.
        # M6-phase-D no longer subscribes to any AP data-store key
        # (outstanding is derived), and display/colors default off so
        # scout warming is skipped.
    })

    assert sw.capturesanity_calls == [False]
    assert sw.push_capturesanity_calls == 1
    assert sw.ap_states == ["ready"]
    # ctx mirror gets flipped too — used by gui.py to hide the
    # "Captures unlocked" section (which would otherwise list 50
    # synthetic unlocks).
    assert ctx.capturesanity_enabled is False


@pytest.mark.asyncio
async def test_connected_handler_pushes_capturesanity_on_to_switch():
    """Symmetric case: when slot_data.capturesanity == 1, the switch
    gets enabled=True and push_capturesanity_replay is still called
    (the method itself is the no-op gate, not the call site)."""
    import asyncio
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    await ctx._handle_ap_package("Connected", {
        "slot_data": {"capturesanity": 1},
    })

    assert sw.capturesanity_calls == [True]
    assert sw.push_capturesanity_calls == 1
    assert ctx.capturesanity_enabled is True


@pytest.mark.asyncio
async def test_connected_handler_tolerates_missing_slot_data():
    """Defensive: a malformed Connected packet (or a server that
    doesn't ship slot_data) must not crash — default to enabled=False
    matches the apworld's default Capturesanity Toggle = OFF."""
    import asyncio
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    # No slot_data key at all.
    await ctx._handle_ap_package("Connected", {})
    assert sw.capturesanity_calls == [False]

    # Explicit None.
    sw.capturesanity_calls.clear()
    await ctx._handle_ap_package("Connected", {"slot_data": None})
    assert sw.capturesanity_calls == [False]


@pytest.mark.asyncio
async def test_connected_handler_honors_slot_data_death_link_on():
    """`death_link: true` in the player YAML lands in slot_data and the
    Connected handler must flip the bridge into DeathLink mode — set the
    local mirror, update the AP "DeathLink" tag, and propagate to the
    Switch (set the flag + push a fresh HelloAck so the Switch stops
    dropping inbound kills in ApState::maybeApplyInboundKill).

    Regression: pre-fix, slot_data["death_link"] was ignored entirely and
    the user had to enable DeathLink via host.yaml / --deathlink / TOML
    config, contradicting the standard AP convention."""
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    # Stub out update_death_link so we don't need a live server connection
    # to observe the call (the real method tries to send_msgs over a
    # non-existent socket otherwise).
    tag_updates: list[bool] = []
    async def _fake_update_death_link(enabled: bool) -> None:
        tag_updates.append(enabled)
        if enabled:
            ctx.tags.add("DeathLink")
        else:
            ctx.tags.discard("DeathLink")
    ctx.update_death_link = _fake_update_death_link  # type: ignore[assignment]

    assert ctx.deathlink_enabled is False

    await ctx._handle_ap_package("Connected", {
        "slot_data": {"capturesanity": 0, "death_link": 1},
    })

    assert ctx.deathlink_enabled is True
    assert "DeathLink" in ctx.tags
    assert tag_updates == [True]
    assert sw.deathlink_calls == [True]
    assert sw.push_deathlink_calls == 1


@pytest.mark.asyncio
async def test_connected_handler_honors_slot_data_death_link_off():
    """Symmetric case: a slot whose YAML explicitly says `death_link: 0`
    forces the bridge off even if it launched with `--deathlink`.

    DeathLink is per-slot (each player opts in via their own YAML; an N-
    player seed can have any subset participating), and slot_data carries
    this player's authoritative choice for this seed. The launch-time
    --deathlink override is legacy/dev — slot_data wins, which also drops
    the "DeathLink" server tag so the player stops receiving deaths from
    the opted-in subset they explicitly opted out of."""
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
        deathlink_enabled=True,  # simulate --deathlink at launch
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    tag_updates: list[bool] = []
    async def _fake_update_death_link(enabled: bool) -> None:
        tag_updates.append(enabled)
        if enabled:
            ctx.tags.add("DeathLink")
        else:
            ctx.tags.discard("DeathLink")
    ctx.update_death_link = _fake_update_death_link  # type: ignore[assignment]

    assert ctx.deathlink_enabled is True

    await ctx._handle_ap_package("Connected", {
        "slot_data": {"capturesanity": 0, "death_link": 0},
    })

    assert ctx.deathlink_enabled is False
    assert "DeathLink" not in ctx.tags
    assert tag_updates == [False]
    assert sw.deathlink_calls == [False]
    assert sw.push_deathlink_calls == 1


@pytest.mark.asyncio
async def test_connected_handler_leaves_deathlink_alone_when_slot_data_absent():
    """Missing `death_link` key (older apworld build) must NOT clobber the
    launch-time setting — silently flipping it would surprise users on an
    old seed mid-session."""
    ctx = SMOContext(
        server_address=None, password=None,
        state=BridgeState(),
        datapackage=DataPackage(),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
        deathlink_enabled=True,
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    update_calls: list[bool] = []
    async def _fake_update_death_link(enabled: bool) -> None:
        update_calls.append(enabled)
    ctx.update_death_link = _fake_update_death_link  # type: ignore[assignment]

    # slot_data present but no death_link key — launch state preserved,
    # no tag update, no push to Switch.
    await ctx._handle_ap_package("Connected", {
        "slot_data": {"capturesanity": 0},
    })

    assert ctx.deathlink_enabled is True
    assert update_calls == []
    assert sw.deathlink_calls == []
    assert sw.push_deathlink_calls == 0


def test_to_ref_preserves_name_for_all_kinds():
    """Pure unit-level guard against re-introducing the OTHER-only conditional."""
    from client.datapackage import ClassifiedItem
    from client.protocol import ItemKind

    for kind, kwargs in [
        (ItemKind.MOON, {"kingdom": "Cascade", "shine_id": "Power Moon"}),
        (ItemKind.CAPTURE, {"cap": "Goomba"}),
        (ItemKind.OTHER, {}),
    ]:
        ci = ClassifiedItem(kind=kind, name=f"test-{kind.value}", **kwargs)
        ref = ci.to_ref()
        assert ref.name == f"test-{kind.value}", (
            f"to_ref() dropped name for kind={kind.value!r}; "
            f"this is the AP-server `?`-display regression."
        )


@pytest.mark.asyncio
async def test_ap_received_moon_sends_both_itemmsg_and_outstandingmsg():
    """Regression for the M6-phase-D double-credit bug.

    On every Moon ReceivedItems batch, the bridge MUST push both an
    ItemMsg (observation + Cappy speech feed on the mod) AND an
    OutstandingMsg (authoritative per-kingdom counter). The Switch's
    Moon-arm in applyOnFrame is a no-op for the counter — if the bridge
    ever sends ItemMsg without the accompanying OutstandingMsg, the
    counter for that kingdom never ticks. Lock in the contract here.
    """
    import asyncio
    state = BridgeState()
    ctx = SMOContext(
        server_address=None, password=None,
        state=state,
        datapackage=DataPackage(apworld_data_dir=_APWORLD_DATA),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    ctx.dp.item_id_to_name[42] = "Cascade Kingdom Power Moon"
    ctx.dp.item_name_to_id["Cascade Kingdom Power Moon"] = 42

    # Seed a PaySnapshot so compute_outstanding has a reading. Without
    # this, the bridge defers OutstandingMsg until the Switch's first
    # PaySnapshotMsg lands (Switch on title screen guard).
    state.apply_pay_snapshot({})

    await ctx._handle_ap_package("ReceivedItems", {
        "items": [{"item": 42, "player": 0, "flags": 0}],
    })
    await asyncio.sleep(0)

    # Exactly one of each, in either order — both are required to keep the
    # mod's ap_moons_kingdom[bit] correct.
    assert len(sw.items) == 1
    assert sw.items[0].kind == "moon"
    assert sw.items[0].kingdom == "Cascade"
    assert len(sw.outstanding) == 1, (
        "Moon grant did not push OutstandingMsg — the Switch counter "
        "would never tick (the mod's ItemMsg-apply path is observation-"
        "only for moons)."
    )
    cascade_count = next(
        (e.count for e in sw.outstanding[0].entries if e.kingdom == "Cascade"),
        None,
    )
    assert cascade_count == 1, (
        f"OutstandingMsg should report Cascade=1 after one grant; "
        f"got entries={sw.outstanding[0].entries!r}"
    )


@pytest.mark.asyncio
async def test_ap_received_multi_moon_batch_debounces_outstanding():
    """Multiple Moon items in one ReceivedItems packet must collapse to
    a single OutstandingMsg push (per the comment at context.py:618-624).

    This is the debounce that keeps reconnect-driven bulk replays from
    flooding the Switch with one OutstandingMsg per item.
    """
    import asyncio
    state = BridgeState()
    ctx = SMOContext(
        server_address=None, password=None,
        state=state,
        datapackage=DataPackage(apworld_data_dir=_APWORLD_DATA),
        shine_map=ShineMap(),
        capture_map=CaptureMap(),
    )
    ctx.auth = "Mario"
    sw = _StubSwitch()
    ctx.switch = sw  # type: ignore[assignment]

    ctx.dp.item_id_to_name[42] = "Cascade Kingdom Power Moon"
    ctx.dp.item_id_to_name[43] = "Sand Kingdom Power Moon"
    ctx.dp.item_id_to_name[44] = "Cascade Kingdom Multi-Moon"
    for nid, nm in ctx.dp.item_id_to_name.items():
        ctx.dp.item_name_to_id[nm] = nid

    # Seed a PaySnapshot so compute_outstanding has a reading.
    state.apply_pay_snapshot({})

    await ctx._handle_ap_package("ReceivedItems", {
        "items": [
            {"item": 42, "player": 0, "flags": 0},
            {"item": 43, "player": 0, "flags": 0},
            {"item": 44, "player": 0, "flags": 0},
        ],
    })
    await asyncio.sleep(0)

    # 3 ItemMsg (one per item), 1 OutstandingMsg (debounced over the batch).
    assert len(sw.items) == 3
    assert len(sw.outstanding) == 1, (
        f"expected 1 debounced OutstandingMsg; got {len(sw.outstanding)}"
    )
    by_kingdom = {e.kingdom: e.count for e in sw.outstanding[0].entries}
    assert by_kingdom.get("Cascade") == 4, (  # 1 Power Moon + 3 Multi-Moon
        f"Cascade should be 4 (1 PM + 3 MM); got {by_kingdom}"
    )
    assert by_kingdom.get("Sand") == 1, (
        f"Sand should be 1; got {by_kingdom}"
    )


# (The M6-phase-D `_outstanding_*` / rii dedup / v1 migration / hydration
# test block was deleted alongside the derivation refactor. Outstanding is
# now derived from (lifetime_received_AP - PayShineNum); the new equivalent
# tests live in test_outstanding.py — see test_crash_rollback_recovers_outstanding
# for the headline bug-class regression.)
