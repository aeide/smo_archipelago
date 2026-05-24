"""Tests for the APPDATA map search path in `client/setup_state.py`.

Covers `_resolve_map_path` precedence (explicit override > APPDATA >
legacy bundled location) and the `_user_data_dir` env-var fallbacks.
SMOClient reads through these helpers on every launch to find the
wizard-produced shine_map.json / capture_map.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from client.setup_state import (
    _resolve_map_path,
    _user_data_dir,
)


@pytest.fixture
def isolated_appdata(monkeypatch, tmp_path: Path) -> Path:
    """Point APPDATA at a tmp dir so tests don't see / touch the real
    %APPDATA%/SMOArchipelago/ (and so this still works in CI where
    APPDATA may be unset)."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path / "SMOArchipelago"


def test_resolve_map_path_prefers_appdata(
    isolated_appdata: Path, monkeypatch
) -> None:
    """When the wizard has written maps to %APPDATA%, that's the path
    `_resolve_map_path` returns — NOT the bundled client/data/ location."""
    data = isolated_appdata / "data"
    data.mkdir(parents=True)
    appdata_shine = data / "shine_map.json"
    appdata_shine.write_text("[]")
    result = _resolve_map_path("", "shine_map.json")
    assert result == appdata_shine


def test_resolve_map_path_explicit_wins(
    isolated_appdata: Path, tmp_path: Path
) -> None:
    """An explicit host.yaml / CLI override beats any auto-discovery —
    matches the existing precedence in `client/main.py:100-135`."""
    data = isolated_appdata / "data"
    data.mkdir(parents=True)
    (data / "shine_map.json").write_text("[]")

    explicit = tmp_path / "custom_shine.json"
    explicit.write_text('[{"stage_name": "X"}]')
    result = _resolve_map_path(str(explicit), "shine_map.json")
    assert result == explicit


def test_resolve_map_path_returns_none_when_none_exist(
    isolated_appdata: Path, monkeypatch
) -> None:
    """No APPDATA, no bundled, no override → returns None so the caller
    falls through to the importlib.resources package-load path (which on
    a release zip also misses and produces empty maps)."""
    # Point setup_state's __file__ at an isolated dir so the legacy
    # client/data/ fallback (relative to that module) doesn't find the
    # real maps in the dev tree.
    import client.setup_state as ss
    fake_module_file = isolated_appdata / "fake_setup_state.py"
    fake_module_file.parent.mkdir(parents=True, exist_ok=True)
    fake_module_file.write_text("")
    monkeypatch.setattr(ss, "__file__", str(fake_module_file))
    result = _resolve_map_path("", "shine_map.json")
    assert result is None


def test_user_data_dir_honors_appdata_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert _user_data_dir() == tmp_path / "SMOArchipelago" / "data"


def test_user_data_dir_falls_back_on_non_windows(monkeypatch) -> None:
    """When APPDATA is unset (Linux/Mac, or stripped Windows env), fall
    back to ~/.local/share/SMOArchipelago/data/."""
    monkeypatch.delenv("APPDATA", raising=False)
    result = _user_data_dir()
    assert result.name == "data"
    assert result.parent.name == "SMOArchipelago"


def test_touch_maps_sentinel_creates_file_and_returns_mtime(
    isolated_appdata: Path,
) -> None:
    """Wizard touches the sentinel after a successful extract; SMOClient
    stats it on AP-Connect to decide whether to reload its maps."""
    from client.setup_state import (
        maps_sentinel_mtime,
        touch_maps_sentinel,
        _sentinel_path,
    )

    # Initially absent → mtime is None.
    assert maps_sentinel_mtime() is None
    assert not _sentinel_path().exists()

    touch_maps_sentinel()
    p = _sentinel_path()
    assert p.exists()
    assert p.parent == isolated_appdata  # %APPDATA%/SMOArchipelago/
    first = maps_sentinel_mtime()
    assert first is not None

    # Idempotent: second touch advances mtime, doesn't error.
    import os, time
    later = first + 5
    os.utime(p, (later, later))
    assert maps_sentinel_mtime() == later


def test_touch_maps_sentinel_creates_parent_dir(
    monkeypatch, tmp_path: Path,
) -> None:
    """Sentinel must be writable even on a fresh machine where neither
    %APPDATA%/SMOArchipelago/ nor its `data/` subdir exists yet — the
    wizard's prereqs phase may have skipped directly to extract."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from client.setup_state import (
        maps_sentinel_mtime,
        touch_maps_sentinel,
    )
    # Nothing exists yet — not even SMOArchipelago/.
    assert not (tmp_path / "SMOArchipelago").exists()
    touch_maps_sentinel()
    assert maps_sentinel_mtime() is not None
