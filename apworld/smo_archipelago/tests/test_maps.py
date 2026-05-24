"""Tests for the bridge's raw-ID resolution tables."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from client.maps import CaptureMap, MoonResolution, ShineMap


def _write(tmp_path: Path, name: str, entries: list) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_shine_map_resolves_by_pair(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "CapWorldHomeStage", "object_id": "MoonOurFirst",
         "kingdom": "Cap", "shine_id": "Our First Power Moon"},
    ])
    m = ShineMap(p)
    res = m.resolve("CapWorldHomeStage", "MoonOurFirst")
    assert res == MoonResolution(kingdom="Cap", shine_id="Our First Power Moon")


def test_shine_map_returns_none_for_unknown(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [])
    m = ShineMap(p)
    assert m.resolve("BogusStage", "MoonBogus") is None


def test_shine_map_falls_back_to_uid(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "X", "object_id": "Y", "shine_uid": 999,
         "kingdom": "Cap", "shine_id": "Test Moon"},
    ])
    m = ShineMap(p)
    # Pair lookup fails (wrong names), so we fall back to uid.
    assert m.resolve("other", "other", 999) is not None


def test_shine_map_handles_missing_file() -> None:
    m = ShineMap(Path("/nonexistent/path/shine_map.json"))
    assert m.resolve("any", "any") is None


def test_shine_map_inverse_lookup_by_location(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "CapWorldHomeStage", "object_id": "MoonOurFirst",
         "kingdom": "Cap", "shine_id": "Our First Power Moon",
         "shine_uid": 42},
        {"stage_name": "WaterfallWorldHomeStage", "object_id": "obj214",
         "kingdom": "Cascade", "shine_id": "Our First Power Moon",
         "shine_uid": 100},
    ])
    m = ShineMap(p)
    # Inverse: (kingdom, shine_id) -> shine_uid. Two entries can share a
    # shine_id (e.g. "Our First Power Moon" appears in multiple kingdoms);
    # the kingdom prefix disambiguates.
    assert m.resolve_uid_by_location("Cap", "Our First Power Moon") == 42
    assert m.resolve_uid_by_location("Cascade", "Our First Power Moon") == 100


def test_shine_map_inverse_lookup_returns_none_for_unknown(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "X", "object_id": "Y", "shine_uid": 1,
         "kingdom": "Cap", "shine_id": "Moon"},
    ])
    m = ShineMap(p)
    assert m.resolve_uid_by_location("Nonexistent", "Moon") is None
    assert m.resolve_uid_by_location("Cap", "Other Moon") is None
    assert m.resolve_uid_by_location(None, "Moon") is None
    assert m.resolve_uid_by_location("Cap", None) is None


def test_shine_map_inverse_skips_entries_without_uid(tmp_path: Path) -> None:
    """Entries without a shine_uid are ignored by the inverse map (you can
    still resolve them by pair, but you can't go backward without a uid)."""
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "X", "object_id": "Y",
         "kingdom": "Cap", "shine_id": "Moon"},  # no shine_uid
    ])
    m = ShineMap(p)
    assert m.resolve_uid_by_location("Cap", "Moon") is None


def test_capture_map_passthrough_when_unmapped(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [])
    m = CaptureMap(p)
    assert m.resolve("Goomba") == "Goomba"  # pass-through


def test_capture_map_translates(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(p)
    assert m.resolve("Kuribo") == "Goomba"
    # Unmapped names still pass through.
    assert m.resolve("Frog") == "Frog"


def test_capture_map_none_input() -> None:
    m = CaptureMap()
    assert m.resolve(None) is None
    assert m.resolve("") is None


# M6 phase B — reverse lookup (cap_name -> hack_name) used by item application.


def test_capture_map_reverse_resolves(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
        {"hack_name": "Pukupuku", "cap": "Cheep Cheep"},
    ])
    m = CaptureMap(p)
    assert m.cap_to_hack("Goomba") == "Kuribo"
    assert m.cap_to_hack("Cheep Cheep") == "Pukupuku"


def test_capture_map_reverse_passthrough_when_unmapped(tmp_path: Path) -> None:
    """Caps not in the map identity-passthrough — covers the 1:1 names."""
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(p)
    assert m.cap_to_hack("Frog") == "Frog"


def test_capture_map_reverse_handles_missing_file() -> None:
    m = CaptureMap(Path("/nonexistent/path/capture_map.json"))
    assert m.cap_to_hack("Goomba") == "Goomba"  # full identity-passthrough


def test_capture_map_reverse_none_input() -> None:
    m = CaptureMap()
    assert m.cap_to_hack(None) is None
    assert m.cap_to_hack("") is None


def test_shine_map_len_reports_loaded_entry_count(tmp_path: Path) -> None:
    p = _write(tmp_path, "shine.json", [
        {"stage_name": "X1", "object_id": "Y1", "kingdom": "Cap", "shine_id": "M1"},
        {"stage_name": "X2", "object_id": "Y2", "kingdom": "Cap", "shine_id": "M2"},
    ])
    assert len(ShineMap(p)) == 2
    assert len(ShineMap()) == 0


def test_capture_map_len_reports_loaded_entry_count(tmp_path: Path) -> None:
    p = _write(tmp_path, "cap.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    assert len(CaptureMap(p)) == 1
    assert len(CaptureMap()) == 0


def test_shine_map_reload_atomically_replaces_table(tmp_path: Path) -> None:
    """`reload` clears the existing in-memory table before loading the
    new one — distinct from `load` which accumulates (used by the
    construction-time package + filesystem layered load)."""
    old = _write(tmp_path, "old.json", [
        {"stage_name": "OldStage", "object_id": "OldObj",
         "kingdom": "Cap", "shine_id": "Old Moon"},
    ])
    m = ShineMap(old)
    assert m.resolve("OldStage", "OldObj") is not None

    new = _write(tmp_path, "new.json", [
        {"stage_name": "NewStage", "object_id": "NewObj",
         "kingdom": "Sand", "shine_id": "New Moon"},
    ])
    n = m.reload(new)
    assert n == 1
    # Old entry must be GONE — not accumulated.
    assert m.resolve("OldStage", "OldObj") is None
    res = m.resolve("NewStage", "NewObj")
    assert res is not None
    assert res.kingdom == "Sand"


def test_capture_map_reload_atomically_replaces_table(tmp_path: Path) -> None:
    old = _write(tmp_path, "old.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(old)
    assert m.cap_to_hack("Goomba") == "Kuribo"

    new = _write(tmp_path, "new.json", [
        {"hack_name": "Pukupuku", "cap": "Cheep Cheep"},
    ])
    n = m.reload(new)
    assert n == 1
    # Old reverse entry must be GONE — falls through to identity passthrough.
    assert m.cap_to_hack("Goomba") == "Goomba"
    assert m.cap_to_hack("Cheep Cheep") == "Pukupuku"


def test_shine_map_reload_preserves_instance_identity(tmp_path: Path) -> None:
    """In-place mutation matters: SwitchServer captures `capture_map.iter_all`
    as a bound method at construction time. If reload swapped the instance,
    the closure would still hold the old (empty) one."""
    old = _write(tmp_path, "old.json", [])
    m = ShineMap(old)
    orig_id = id(m)
    new = _write(tmp_path, "new.json", [
        {"stage_name": "S", "object_id": "O", "kingdom": "Cap", "shine_id": "X"},
    ])
    m.reload(new)
    assert id(m) == orig_id
    assert len(m) == 1


def test_shine_map_reload_leaves_state_intact_on_malformed_input(
    tmp_path: Path,
) -> None:
    """A malformed reload must NOT wipe the in-memory map — otherwise
    a user who accidentally truncates shine_map.json would lose their
    working SMOClient state on the next reload trigger."""
    good = _write(tmp_path, "good.json", [
        {"stage_name": "S", "object_id": "O", "kingdom": "Cap", "shine_id": "M"},
    ])
    m = ShineMap(good)
    assert len(m) == 1

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(Exception):
        m.reload(bad)
    # State preserved.
    assert len(m) == 1
    assert m.resolve("S", "O") is not None


def test_capture_map_reload_leaves_state_intact_on_malformed_input(
    tmp_path: Path,
) -> None:
    good = _write(tmp_path, "good.json", [
        {"hack_name": "Kuribo", "cap": "Goomba"},
    ])
    m = CaptureMap(good)
    assert len(m) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("xxx", encoding="utf-8")
    with pytest.raises(Exception):
        m.reload(bad)
    assert len(m) == 1
    assert m.cap_to_hack("Goomba") == "Kuribo"
