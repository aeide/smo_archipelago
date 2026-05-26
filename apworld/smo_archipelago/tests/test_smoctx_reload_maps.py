"""Tests for SMOContext.reload_maps + report_check miss-path lazy reload.

Covers the two fix paths that close the "user ran wizard but never
restarted SMOClient" loop (see CLAUDE.md "Status" and the 2026-05-23
bridge logs that motivated this work):

  - Sentinel-driven reload at AP-Connect: the wizard touches
    `<%APPDATA%>/SMOArchipelago/.maps-updated` on successful extract;
    SMOContext stats it and reloads on every Connected where the mtime
    is newer than the last load.

  - Force-driven reload from `report_check`'s miss path: a moon
    collection whose `(stage_name, object_id)` can't be resolved
    triggers an immediate reload (bypassing the mtime gate) and a
    retry. If still unresolved, a one-shot user-visible warning surfaces
    in the Kivy chat panel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add vendor/Archipelago BEFORE the import-skip so CommonClient is reachable.
_AP = Path(__file__).resolve().parents[3] / "vendor" / "Archipelago"
if _AP.exists() and str(_AP) not in sys.path:
    sys.path.insert(0, str(_AP))

try:  # pragma: no cover
    import ModuleUpdate  # type: ignore[import-not-found]
    ModuleUpdate.update_ran = True
except ImportError:
    pass

CommonClient = pytest.importorskip(
    "CommonClient",
    reason="Archipelago checkout not present; init the vendor/Archipelago submodule.",
)

# Pre-register Spicy Meatball Overdrive in network_data_package so
# CommonContext.__init__ (which reads `self.checksums[self.game]`) doesn't
# KeyError. In a real apworld install the entry is populated by
# AutoWorldRegister; the test env doesn't go through that path.
from worlds import network_data_package as _ndp  # type: ignore[attr-defined]
_ndp.setdefault("games", {}).setdefault(
    "Spicy Meatball Overdrive",
    {"checksum": "0" * 64, "item_name_to_id": {}, "location_name_to_id": {}},
)

from client.context import SMOContext  # noqa: E402
from client.datapackage import DataPackage  # noqa: E402
from client.maps import CaptureMap, ShineMap  # noqa: E402
from client.state import BridgeState  # noqa: E402


_STAGE = "WaterfallWorldHomeStage"
_OBJ = "obj214"
_KINGDOM = "Cascade"
_SHINE_ID = "Our First Power Moon"
_LOC_NAME = f"{_KINGDOM}: {_SHINE_ID}"  # matches SMOContext._reconstruct_location_name
_LOC_ID = 13404070123


@pytest.fixture
def isolated_appdata(monkeypatch, tmp_path: Path) -> Path:
    """Isolate APPDATA so the sentinel + maps don't touch the real user dir.

    Also pre-creates empty stub map files so _resolve_map_path's step-3
    client/data/ fallback never fires — without the stubs, a developer who
    has run the extractor would have real shine_map.json / capture_map.json
    in client/data/, and those would leak into tests that expect empty maps.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata = tmp_path / "SMOArchipelago"
    data_dir = appdata / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "shine_map.json").write_text("[]", encoding="utf-8")
    (data_dir / "capture_map.json").write_text("[]", encoding="utf-8")
    return appdata


def _write_json(path: Path, entries: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _make_ctx(
    *,
    shine_map: ShineMap | None = None,
    capture_map: CaptureMap | None = None,
    shine_map_path: str = "",
    capture_map_path: str = "",
    register_loc: bool = True,
) -> SMOContext:
    dp = DataPackage()
    if register_loc:
        dp.location_id_to_name[_LOC_ID] = _LOC_NAME
        dp.location_name_to_id[_LOC_NAME] = _LOC_ID
    ctx = SMOContext(
        server_address=None,
        password=None,
        state=BridgeState(),
        datapackage=dp,
        shine_map=shine_map if shine_map is not None else ShineMap(),
        capture_map=capture_map if capture_map is not None else CaptureMap(),
        shine_map_path=shine_map_path,
        capture_map_path=capture_map_path,
    )
    ctx.auth = "Mario"
    ctx.slot = 1
    ctx.team = 0
    return ctx


def _write_canonical_shine(appdata: Path) -> Path:
    data_dir = appdata / "data"
    return _write_json(data_dir / "shine_map.json", [
        {"stage_name": _STAGE, "object_id": _OBJ, "shine_uid": 1,
         "kingdom": _KINGDOM, "shine_id": _SHINE_ID},
    ])


# ---------------------------------------------------------------------------
# reload_maps() core behavior
# ---------------------------------------------------------------------------

async def test_reload_maps_returns_false_when_no_sentinel(
    isolated_appdata: Path,
) -> None:
    """No sentinel + never-reloaded ⇒ skip without filesystem access.

    Matters because the sentinel-driven Connected handler runs on every
    reconnect, not just first connect — we don't want every reconnect
    re-stat-ing %APPDATA% when nothing has changed."""
    ctx = _make_ctx()
    assert ctx.reload_maps() == (False, False)


async def test_reload_maps_loads_shine_when_sentinel_appears(
    isolated_appdata: Path,
) -> None:
    """Wizard ran while SMOClient was up: sentinel now exists with a
    fresh mtime, and the maps are in %APPDATA%. Connected handler's
    reload_maps() should pick them up."""
    from client.setup_state import touch_maps_sentinel

    ctx = _make_ctx()
    assert len(ctx.shine_map) == 0

    _write_canonical_shine(isolated_appdata)
    touch_maps_sentinel()

    shine_new, _ = ctx.reload_maps()
    assert shine_new is True
    assert len(ctx.shine_map) == 1
    assert ctx.shine_map.resolve(_STAGE, _OBJ) is not None


async def test_reload_maps_skips_when_sentinel_unchanged(
    isolated_appdata: Path,
) -> None:
    """Sentinel mtime matches what we loaded last time ⇒ skip the
    re-stat. Avoids reloading the same content on every reconnect."""
    from client.setup_state import touch_maps_sentinel

    _write_canonical_shine(isolated_appdata)
    touch_maps_sentinel()

    ctx = _make_ctx()
    assert ctx.reload_maps() == (True, False)

    # Second call against the same sentinel mtime: must be a no-op.
    assert ctx.reload_maps() == (False, False)


async def test_reload_maps_force_bypasses_sentinel_gate(
    isolated_appdata: Path,
) -> None:
    """`force=True` from the miss path skips the mtime check — a missed
    shine lookup is a stronger signal than the sentinel."""
    _write_canonical_shine(isolated_appdata)
    # No sentinel touched at all — simulates user manually copying maps
    # without re-running the wizard.

    ctx = _make_ctx()
    # Without force, no sentinel ⇒ no reload.
    assert ctx.reload_maps() == (False, False)
    assert len(ctx.shine_map) == 0

    # With force, the maps are found and loaded.
    shine_new, _ = ctx.reload_maps(force=True)
    assert shine_new is True
    assert len(ctx.shine_map) == 1


async def test_reload_maps_preserves_instance_identity(
    isolated_appdata: Path,
) -> None:
    """SwitchServer captures `capture_map.iter_all` as a bound method
    at construction time. If reload_maps swapped the instance, the
    closure would still hold the OLD (empty) one."""
    ctx = _make_ctx()
    orig_shine_id = id(ctx.shine_map)
    orig_cap_id = id(ctx.capture_map)

    _write_canonical_shine(isolated_appdata)
    _write_json(isolated_appdata / "data" / "capture_map.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    from client.setup_state import touch_maps_sentinel
    touch_maps_sentinel()

    ctx.reload_maps()
    assert id(ctx.shine_map) == orig_shine_id
    assert id(ctx.capture_map) == orig_cap_id


async def test_reload_maps_honors_explicit_path_override(
    isolated_appdata: Path, tmp_path: Path,
) -> None:
    """host.yaml / CLI explicit shine_map_path wins over APPDATA — same
    precedence as the launch-time `_resolve_map_path` chain."""
    # APPDATA copy has one entry; explicit override has two.
    _write_canonical_shine(isolated_appdata)
    explicit = _write_json(tmp_path / "explicit_shine.json", [
        {"stage_name": "S1", "object_id": "O1", "kingdom": "Cap", "shine_id": "M1"},
        {"stage_name": "S2", "object_id": "O2", "kingdom": "Cap", "shine_id": "M2"},
    ])
    from client.setup_state import touch_maps_sentinel
    touch_maps_sentinel()

    ctx = _make_ctx(shine_map_path=str(explicit))
    ctx.reload_maps(force=True)
    assert len(ctx.shine_map) == 2


# ---------------------------------------------------------------------------
# report_check miss path → lazy reload + user-visible warning
# ---------------------------------------------------------------------------

class _OutputCapture:
    """Capture self.output(...) calls so we can assert on the
    user-visible chat panel content."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str) -> None:
        self.lines.append(text)


async def _drive_report_moon(
    ctx: SMOContext,
    *,
    sent: list[Any] | None = None,
    stage_name: str = _STAGE,
    object_id: str = _OBJ,
) -> Any:
    """Run `report_check` for a moon and capture any AP-bound LocationChecks."""
    if sent is not None:
        async def _record(msgs):
            sent.extend(msgs)
        ctx.send_msgs = _record  # type: ignore[assignment]
    return await ctx.report_check(
        kind="moon",
        stage_name=stage_name,
        object_id=object_id,
    )


async def test_report_check_miss_triggers_lazy_reload_and_succeeds(
    isolated_appdata: Path,
) -> None:
    """The 2026-05-23 user case: SMOClient started with empty maps,
    user ran wizard mid-session (maps now on disk), then collected a
    moon. The first moon should trigger the lazy reload and succeed."""
    ctx = _make_ctx()
    ctx.output = _OutputCapture()  # type: ignore[assignment]

    # Maps appear on disk AFTER ctx was built — no sentinel touched.
    _write_canonical_shine(isolated_appdata)

    sent: list[Any] = []
    loc_id = await _drive_report_moon(ctx, sent=sent)
    assert loc_id == _LOC_ID
    assert sent == [{"cmd": "LocationChecks", "locations": [_LOC_ID]}]
    # Reload populated the map.
    assert len(ctx.shine_map) == 1
    # No user warning — the reload covered for it.
    assert ctx.output.lines == []  # type: ignore[attr-defined]


async def test_report_check_persistent_miss_surfaces_user_warning(
    isolated_appdata: Path,
) -> None:
    """No maps on disk anywhere ⇒ reload finds nothing ⇒ user-visible
    warning fires once. Subsequent misses stay quiet (one-shot)."""
    ctx = _make_ctx()
    capture = _OutputCapture()
    ctx.output = capture  # type: ignore[assignment]

    sent: list[Any] = []
    assert (await _drive_report_moon(ctx, sent=sent)) is None
    assert sent == []
    assert len(capture.lines) == 1
    assert "shine_map.json is empty" in capture.lines[0]

    # Second miss: same one-shot warning suppressed.
    assert (await _drive_report_moon(ctx)) is None
    assert len(capture.lines) == 1


async def test_report_check_one_shot_rearms_after_successful_reload(
    isolated_appdata: Path,
) -> None:
    """After a successful reload populates the map, a future miss
    against an entry the map STILL doesn't have should warn again.
    Re-arming the one-shot guard is what makes the warning useful for
    iterative extraction (user re-runs wizard, picks up some moons,
    still has gaps)."""
    ctx = _make_ctx()
    capture = _OutputCapture()
    ctx.output = capture  # type: ignore[assignment]

    # First miss: empty map ⇒ warning fires.
    assert (await _drive_report_moon(ctx)) is None
    assert len(capture.lines) == 1

    # Wizard runs: maps land on disk + sentinel touched.
    _write_canonical_shine(isolated_appdata)
    from client.setup_state import touch_maps_sentinel
    touch_maps_sentinel()
    shine_new, _ = ctx.reload_maps()
    assert shine_new is True

    # Now collect a DIFFERENT moon that the map still doesn't cover.
    sent: list[Any] = []
    result = await _drive_report_moon(
        ctx, sent=sent,
        stage_name="UnmappedStage", object_id="obj999",
    )
    assert result is None
    # Re-armed by reload_maps; second warning fires (different shape
    # because the map is non-empty now).
    assert len(capture.lines) == 2
    assert "shine_map.json has" in capture.lines[1]
    assert "entries but none match" in capture.lines[1]


async def test_report_check_known_moon_does_not_trigger_warning(
    isolated_appdata: Path,
) -> None:
    """Smoke check: the normal happy path (map populated at startup,
    moon resolves cleanly) doesn't trip any of the reload / warning
    machinery."""
    _write_canonical_shine(isolated_appdata)
    shine_map = ShineMap(isolated_appdata / "data" / "shine_map.json")
    ctx = _make_ctx(shine_map=shine_map)
    capture = _OutputCapture()
    ctx.output = capture  # type: ignore[assignment]

    sent: list[Any] = []
    loc_id = await _drive_report_moon(ctx, sent=sent)
    assert loc_id == _LOC_ID
    assert capture.lines == []


async def test_reload_maps_refuses_to_replace_populated_with_empty(
    isolated_appdata: Path,
) -> None:
    """No-clobber guard: a truncated / accidentally-emptied
    shine_map.json on disk must NOT nuke the working in-memory map.
    The user might run /setup, the wizard might crash mid-extract and
    leave a `[]` stub — and the player's still mid-collection. We log
    a warning and keep the in-memory copy alive."""
    # Start with a populated in-memory map.
    _write_canonical_shine(isolated_appdata)
    shine_map = ShineMap(isolated_appdata / "data" / "shine_map.json")
    assert len(shine_map) == 1
    ctx = _make_ctx(shine_map=shine_map)

    # Truncate the file on disk to an empty list + touch sentinel.
    _write_json(isolated_appdata / "data" / "shine_map.json", [])
    from client.setup_state import touch_maps_sentinel
    touch_maps_sentinel()

    shine_new, _ = ctx.reload_maps()
    # Reload skipped the swap → in-memory map intact.
    assert shine_new is False
    assert len(ctx.shine_map) == 1
    assert ctx.shine_map.resolve(_STAGE, _OBJ) is not None
