"""Tests for `_setup.wizard._resolve_persisted_path`.

The wizard persists user-chosen `hactool_path` and `prodkeys_path` to
`setup_state.json` after the prereq check passes, then the extract
worker reads those back on a later run. If the user moved either file
in between (re-mounted their key drive, archived an old hactool build,
etc.), the stale path would be passed to a subprocess and fail far
downstream with a cryptic message. This helper catches the staleness
at the wizard layer and surfaces a clear "fall back to auto-detect"
breadcrumb instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _setup.wizard import _resolve_persisted_path


def test_returns_none_when_key_missing() -> None:
    assert _resolve_persisted_path({}, "hactool_path") is None


def test_returns_none_when_value_is_none() -> None:
    assert _resolve_persisted_path({"hactool_path": None}, "hactool_path") is None


def test_returns_none_when_value_is_empty_string() -> None:
    assert _resolve_persisted_path({"hactool_path": ""}, "hactool_path") is None


def test_returns_none_when_value_is_wrong_type(tmp_path: Path) -> None:
    """A hand-edited setup_state.json could put a non-string here — the
    old code (`Path(state["hactool_path"])`) would crash with TypeError
    deep inside the worker."""
    log_lines: list[str] = []
    result = _resolve_persisted_path(
        {"hactool_path": 12345},
        "hactool_path",
        on_line=log_lines.append,
    )
    assert result is None
    assert any("expected a non-empty string" in line for line in log_lines)


def test_returns_none_when_file_no_longer_exists(tmp_path: Path) -> None:
    """The user picked a hactool, the wizard persisted it, then the
    user moved/archived the binary. Helper must return None and log a
    clear breadcrumb instead of returning a stale Path that would fail
    later inside the extract subprocess with an opaque message."""
    log_lines: list[str] = []
    moved_path = tmp_path / "moved_away" / "hactool.exe"
    result = _resolve_persisted_path(
        {"hactool_path": str(moved_path)},
        "hactool_path",
        on_line=log_lines.append,
    )
    assert result is None
    assert any(str(moved_path) in line for line in log_lines)
    assert any("no longer exists" in line for line in log_lines)


def test_returns_path_when_file_present(tmp_path: Path) -> None:
    f = tmp_path / "hactool.exe"
    f.write_bytes(b"")
    result = _resolve_persisted_path(
        {"hactool_path": str(f)},
        "hactool_path",
    )
    assert result == f


def test_returns_none_for_directory(tmp_path: Path) -> None:
    """A directory at the persisted path means the user picked the
    folder instead of the binary. is_file() rejects it; the helper
    must too (passing a directory to a subprocess's argv produces a
    confusing 'permission denied' on Windows)."""
    d = tmp_path / "not_a_file"
    d.mkdir()
    result = _resolve_persisted_path(
        {"hactool_path": str(d)},
        "hactool_path",
    )
    assert result is None


def test_on_line_optional() -> None:
    """All branches must work without an on_line callback — the
    extract worker passes one, but the prereq page caller may not."""
    # Missing key → None, no crash.
    assert _resolve_persisted_path({}, "hactool_path") is None
    # Stale path → None, no crash.
    assert _resolve_persisted_path(
        {"hactool_path": "/does/not/exist"}, "hactool_path"
    ) is None


# ---------------------------------------------------------------------------
# Retry cap — surfaced as a module constant so the wizard's extract +
# build pages can share it and tests can pin it.
# ---------------------------------------------------------------------------

def test_max_step_attempts_is_finite_and_sensible() -> None:
    """MAX_STEP_ATTEMPTS guards the extract and build pages' Retry
    buttons so a persistently failing step can't loop forever. Bounds:
    >=2 so users get at least one retry of a transient failure
    (network blip, AV scan), <=10 so the user isn't sitting through
    a dozen failed runs before seeing the "stop and diagnose" message."""
    from _setup.wizard import MAX_STEP_ATTEMPTS
    assert isinstance(MAX_STEP_ATTEMPTS, int)
    assert 2 <= MAX_STEP_ATTEMPTS <= 10, (
        f"MAX_STEP_ATTEMPTS={MAX_STEP_ATTEMPTS} is outside the sensible "
        f"range — too low frustrates users on flaky transient failures, "
        f"too high lets a persistently broken setup retry indefinitely"
    )
