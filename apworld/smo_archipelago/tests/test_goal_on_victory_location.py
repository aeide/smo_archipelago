"""Tests for bridge-side goal handling.

Vanilla SMO awards NO Power Moon for clearing the main game — Mario is
deposited in Mushroom Kingdom by the post-wedding cutscene with nothing
to collect. The Switch detects this via the first 0→1 flip of
`ApState::visited_kingdoms[Mushroom]` (set from
`WorldMapSelectHook::markVisitedFromStage`) and emits a `goal` wire
message.

The bridge side is just: `SwitchServer._on_goal` -> `ctx.report_goal()`
-> AP `StatusUpdate{ClientGoal}`, with a one-shot latch so snapshot
replays across reconnects don't reprint the log line on every (re)connect.

This file replaces the previous moon-check-resolution path
(`MOON_NAME_ALIASES["Moon: Long Journey's End"] -> "Defeat Bowser and
Escape the Moon"`), which fired in the wrong scenarios — "Long Journey's
End" turned out to be the Darker Side completion moon, not the main-game
ending, and there's no main-game completion moon to hook at all.
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
