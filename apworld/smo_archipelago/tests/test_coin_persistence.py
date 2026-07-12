"""Tests for client/coin_state.py — per-save applied-coin persistence.

The Switch's coins_applied high-water mark resets to 0 every game boot while
SMO persists coins, so the client remembers per (seed, slot) how many coins are
already in the save and ships it as CoinGrant.baseline. These tests pin the
persistence contract: round-trip, monotonicity, empty-key guard, and tolerance
of a missing/corrupt file. Runtime (client is importable — no Archipelago deps).
"""

from __future__ import annotations

import importlib

import pytest

coin_state = importlib.import_module("client.coin_state")


@pytest.fixture()
def isolated_appdata(tmp_path, monkeypatch):
    # coin_state locates its file via setup_state._user_data_dir(), which reads
    # %APPDATA%. Point it at a tmp dir so the test never touches the real one.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # A prior test in the same process may have imported with a different
    # APPDATA; the function reads the env each call, so nothing to reset.
    return tmp_path


def test_load_unknown_returns_zero(isolated_appdata):
    assert coin_state.load_applied("seedA", "Player1") == 0


def test_roundtrip(isolated_appdata):
    coin_state.save_applied("seedA", "Player1", 500)
    assert coin_state.load_applied("seedA", "Player1") == 500


def test_keys_are_per_seed_and_slot(isolated_appdata):
    coin_state.save_applied("seedA", "Player1", 500)
    coin_state.save_applied("seedA", "Player2", 300)
    coin_state.save_applied("seedB", "Player1", 100)
    assert coin_state.load_applied("seedA", "Player1") == 500
    assert coin_state.load_applied("seedA", "Player2") == 300
    assert coin_state.load_applied("seedB", "Player1") == 100
    assert coin_state.load_applied("seedC", "Player1") == 0


def test_monotonic_never_lowers(isolated_appdata):
    coin_state.save_applied("seedA", "Player1", 500)
    coin_state.save_applied("seedA", "Player1", 300)  # stale/lower push
    assert coin_state.load_applied("seedA", "Player1") == 500
    coin_state.save_applied("seedA", "Player1", 700)  # genuine increase
    assert coin_state.load_applied("seedA", "Player1") == 700


def test_empty_seed_or_slot_is_noop(isolated_appdata):
    coin_state.save_applied("", "Player1", 500)
    coin_state.save_applied("seedA", "", 500)
    assert coin_state.load_applied("", "Player1") == 0
    assert coin_state.load_applied("seedA", "") == 0
    # And no spurious file/entries were written for a real key.
    assert coin_state.load_applied("seedA", "Player1") == 0


def test_corrupt_file_tolerated(isolated_appdata):
    coin_state._coins_path().parent.mkdir(parents=True, exist_ok=True)
    coin_state._coins_path().write_text("{not valid json", encoding="utf-8")
    assert coin_state.load_applied("seedA", "Player1") == 0
    # A save over a corrupt file recovers cleanly.
    coin_state.save_applied("seedA", "Player1", 250)
    assert coin_state.load_applied("seedA", "Player1") == 250
