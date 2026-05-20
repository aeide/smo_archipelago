"""Tests for bridge-side goal handling.

Vanilla SMO awards NO Power Moon for clearing the main game — Mario is
deposited in Mushroom Kingdom by the post-wedding cutscene with nothing
to collect. The Switch detects "main game cleared" via `CreditsStartHook`
(inline patch at offset 0x4C54A4, the BL inside `StaffRollScene::init`)
and emits a one-shot `goal` wire message.

The bridge side is just: `SwitchServer._on_goal` -> `ctx.report_goal()`
-> AP `StatusUpdate{ClientGoal}`, with a one-shot latch so snapshot
replays across reconnects don't reprint the log line on every (re)connect.

This trigger replaces three earlier wrong paths: a moon-check resolution
(`MOON_NAME_ALIASES["Moon: Long Journey's End"]` — fired on Darker Side
completion); `DemoPeachWedding::makeActorAlive` (also fired in Bowser's
Kingdom); and "first Mushroom Kingdom arrival" (false-fires on the
Luncheon portrait warp). The credits scene only initializes when the
post-wedding cutscene actually plays, so it's the only no-false-positive
signal.
"""

from __future__ import annotations

import json
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

from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


def _make_ctx(shine_map: ShineMap | None = None) -> SMOContext:
    state = BridgeState()
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=state,
        datapackage=DataPackage(),
        shine_map=shine_map or ShineMap(),
        capture_map=CaptureMap(),
        # Suppress the scout-cache warmup in the Connected handler — it
        # would otherwise emit a LocationScouts in our test and complicate
        # the assertions.
        display_enabled=False,
    )
    ctx.colors.enabled = False
    return ctx


def _shine_map_with_one_moon(tmp_path: Path) -> ShineMap:
    p = tmp_path / "shine_map.json"
    p.write_text(json.dumps([{
        "stage_name": "CapWorldHomeStage",
        "object_id": "MoonOurFirst",
        "kingdom": "Cap",
        "shine_id": "Our First Power Moon",
    }]), encoding="utf-8")
    return ShineMap(p)


def _install_send_capture(ctx: SMOContext) -> list[dict]:
    """Replace ctx.send_msgs with a capturer that records each outbound
    AP command. Returns the list (mutated in place)."""
    captured: list[dict] = []

    async def fake_send_msgs(msgs: list[dict]) -> None:
        captured.extend(msgs)

    ctx.send_msgs = fake_send_msgs  # type: ignore[method-assign]
    return captured


@pytest.mark.asyncio
async def test_report_goal_ships_client_goal_status_update():
    """The single producer (`report_goal`) emits one StatusUpdate with
    CLIENT_GOAL and flips the latch."""
    ctx = _make_ctx()
    sent = _install_send_capture(ctx)

    assert ctx._goal_reported is False
    await ctx.report_goal()

    cmds = [m["cmd"] for m in sent]
    assert cmds == ["StatusUpdate"]
    assert sent[0]["status"] == 30  # ClientStatus.CLIENT_GOAL
    assert ctx._goal_reported is True


@pytest.mark.asyncio
async def test_report_goal_is_idempotent():
    """Snapshot replays across reconnects can re-fire `_on_goal`; the
    latch must keep us from spamming AP."""
    ctx = _make_ctx()
    sent = _install_send_capture(ctx)

    await ctx.report_goal()
    await ctx.report_goal()
    await ctx.report_goal()

    assert [m["cmd"] for m in sent] == ["StatusUpdate"]
    assert ctx._goal_reported is True


@pytest.mark.asyncio
async def test_report_check_does_not_fire_goal(tmp_path: Path):
    """No moon check should trigger goal — the Switch's `goal` wire
    message is the only producer now. This guards against accidental
    regressions where someone re-introduces a moon-name → goal mapping."""
    ctx = _make_ctx(_shine_map_with_one_moon(tmp_path))
    sent = _install_send_capture(ctx)

    # Hand-install the moon's loc id (the real datapackage would carry it).
    ctx.dp.location_name_to_id["Cap: Our First Power Moon"] = 70002
    ctx.dp.location_id_to_name[70002] = "Cap: Our First Power Moon"

    await ctx.report_check(
        kind="moon",
        stage_name="CapWorldHomeStage",
        object_id="MoonOurFirst",
    )

    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks"]
    assert ctx._goal_reported is False


def _shine_map_with_festival(tmp_path: Path) -> ShineMap:
    """Shine map that resolves to the festival victory moon."""
    p = tmp_path / "shine_map.json"
    p.write_text(json.dumps([{
        "stage_name": "CityWorldHomeStage",
        "object_id": "MoonFestival",
        "kingdom": "Metro",
        "shine_id": "A Traditional Festival!",
    }]), encoding="utf-8")
    return ShineMap(p)


@pytest.mark.asyncio
async def test_report_check_fires_goal_for_festival_victory(tmp_path: Path):
    """Festival mode: collecting the festival moon must fire ClientGoal.
    AP server-side detection doesn't run (apworld nulls the victory
    location's address), so the bridge tees report_goal off report_check."""
    ctx = _make_ctx(_shine_map_with_festival(tmp_path))
    # Simulate the Connected handler having read slot_data.goal == 1.
    ctx._goal_location_name = "Metro: A Traditional Festival!"
    sent = _install_send_capture(ctx)

    ctx.dp.location_name_to_id["Metro: A Traditional Festival!"] = 70001
    ctx.dp.location_id_to_name[70001] = "Metro: A Traditional Festival!"

    await ctx.report_check(
        kind="moon",
        stage_name="CityWorldHomeStage",
        object_id="MoonFestival",
    )

    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks", "StatusUpdate"]
    assert sent[1]["status"] == 30  # ClientStatus.CLIENT_GOAL
    assert ctx._goal_reported is True


@pytest.mark.asyncio
async def test_outstanding_to_switch_zeros_metro_plus_in_festival_mode():
    """Festival mode: the OutstandingEntry list shipped to the Switch
    must report 0 for Metro and every downstream kingdom regardless of
    what the bridge actually received from AP. Mushroom mode passes
    through real counts."""
    ctx = _make_ctx()
    # Hand-populate the bridge state so compute_outstanding returns
    # something — lifetime_received[K] - pay[K] both per-kingdom.
    ctx.state.moons_received_by_kingdom = {
        "Cap": 3, "Cascade": 7, "Sand": 12, "Lake": 5, "Wooded": 18,
        "Lost": 10, "Metro": 15, "Snow": 4, "Seaside": 2, "Luncheon": 1,
        "Ruined": 1, "Bowser's": 2, "Moon": 0,
    }
    ctx.state.apply_pay_snapshot({})  # zero pay → outstanding == lifetime

    # Mushroom mode (default _goal_location_name=None): real counts.
    entries = ctx._outstanding_entries_for_switch()
    by_kingdom = {e.kingdom: e.count for e in entries}
    assert by_kingdom["Metro"] == 15
    assert by_kingdom["Snow"] == 4
    assert by_kingdom["Cascade"] == 7  # pre-Metro untouched

    # Festival mode: Metro and every kingdom downstream clamped to 0,
    # pre-Metro kingdoms still pass through real counts.
    ctx._goal_location_name = "Metro: A Traditional Festival!"
    entries = ctx._outstanding_entries_for_switch()
    by_kingdom = {e.kingdom: e.count for e in entries}
    for k in ("Metro", "Snow", "Seaside", "Luncheon", "Ruined", "Bowser's", "Moon"):
        assert by_kingdom[k] == 0, f"{k} not zeroed in festival mode: {by_kingdom[k]}"
    for k in ("Cap", "Cascade", "Sand", "Lake", "Wooded", "Lost"):
        assert by_kingdom[k] > 0, f"{k} got clobbered in festival mode"


@pytest.mark.asyncio
async def test_is_festival_goal_predicate():
    """is_festival_goal flips with the slot_data-derived goal location."""
    ctx = _make_ctx()
    assert ctx.is_festival_goal() is False  # default = mushroom mode
    ctx._goal_location_name = "Metro: A Traditional Festival!"
    assert ctx.is_festival_goal() is True
    ctx._goal_location_name = "Some Future Goal!"  # other non-None values
    assert ctx.is_festival_goal() is False


@pytest.mark.asyncio
async def test_report_check_does_not_fire_goal_in_mushroom_mode(tmp_path: Path):
    """Mushroom mode: collecting the festival moon (a real in-game moon
    that happens to exist server-side too) must NOT fire goal — the
    credits hook is the sole producer in that mode."""
    ctx = _make_ctx(_shine_map_with_festival(tmp_path))
    # Mushroom mode: no goal-trigger location on the bridge.
    assert ctx._goal_location_name is None
    sent = _install_send_capture(ctx)

    ctx.dp.location_name_to_id["Metro: A Traditional Festival!"] = 70001
    ctx.dp.location_id_to_name[70001] = "Metro: A Traditional Festival!"

    await ctx.report_check(
        kind="moon",
        stage_name="CityWorldHomeStage",
        object_id="MoonFestival",
    )

    cmds = [m["cmd"] for m in sent]
    assert cmds == ["LocationChecks"]
    assert ctx._goal_reported is False
