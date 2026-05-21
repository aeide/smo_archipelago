"""Tests for `_setup.build.verify_map_hashes`.

The check exists because shine_map.json / capture_map.json are
deterministic across every legitimate SMO 1.0.0 source (eShop NSP,
cartridge dump, XCI, any valid ticket) — they're built from the USen
locale data which is identical across regional SKUs. A hash mismatch is
therefore a real "wrong dump" signal (typically a v1.1.0+ patched build,
a different game, or a corrupted dump), and the wizard uses it as a
hard gate after extraction. These tests pin that contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from _setup.build import (
    EXPECTED_MAP_SHA256,
    MapHashCheck,
    verify_map_hashes,
)


@pytest.fixture
def isolated_appdata(monkeypatch, tmp_path: Path) -> Path:
    """Redirect %APPDATA% so verify_map_hashes reads from a tmp dir."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path / "SMOArchipelago" / "data"


def _write(p: Path, content: bytes) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_expected_hashes_are_sha256_hex() -> None:
    """Canary so a typo'd or truncated fingerprint never silently passes."""
    assert set(EXPECTED_MAP_SHA256) == {"shine_map.json", "capture_map.json"}
    for name, h in EXPECTED_MAP_SHA256.items():
        assert len(h) == 64, f"{name}: expected 64 hex chars, got {len(h)}"
        int(h, 16)  # raises if non-hex


def test_verify_reports_missing_when_files_absent(isolated_appdata: Path) -> None:
    checks = verify_map_hashes()
    assert {c.filename for c in checks} == set(EXPECTED_MAP_SHA256)
    for c in checks:
        assert isinstance(c, MapHashCheck)
        assert c.present is False
        assert c.match is False
        assert c.actual == ""


def test_verify_match_when_bytes_equal_expected(
    isolated_appdata: Path, monkeypatch
) -> None:
    """Substitute known content + matching expected hashes so the test
    doesn't depend on shipping any Nintendo-derived bytes."""
    fake_shine = b'[{"stage_name": "X"}]\n'
    fake_cap = b'[{"hack_name": "Y", "cap": "Z"}]\n'
    h_shine = _write(isolated_appdata / "shine_map.json", fake_shine)
    h_cap = _write(isolated_appdata / "capture_map.json", fake_cap)

    monkeypatch.setattr(
        "_setup.build.EXPECTED_MAP_SHA256",
        {"shine_map.json": h_shine, "capture_map.json": h_cap},
    )

    checks = verify_map_hashes()
    by_name = {c.filename: c for c in checks}
    assert by_name["shine_map.json"].present
    assert by_name["shine_map.json"].match
    assert by_name["shine_map.json"].actual == h_shine
    assert by_name["capture_map.json"].present
    assert by_name["capture_map.json"].match
    assert by_name["capture_map.json"].actual == h_cap


def test_verify_reports_mismatch_when_bytes_differ(
    isolated_appdata: Path, monkeypatch
) -> None:
    _write(isolated_appdata / "shine_map.json", b"not the canonical bytes\n")
    _write(isolated_appdata / "capture_map.json", b"also not canonical\n")

    monkeypatch.setattr(
        "_setup.build.EXPECTED_MAP_SHA256",
        {"shine_map.json": "0" * 64, "capture_map.json": "0" * 64},
    )

    checks = verify_map_hashes()
    for c in checks:
        assert c.present is True
        assert c.match is False
        assert c.actual != "" and c.actual != c.expected
