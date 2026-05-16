"""Unit tests for the bridge REPL command parser.

These cover the pure `parse_command` function — no asyncio, no stdin.
The I/O loop is exercised end-to-end via Ryujinx playtest, not unit tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smo_ap_bridge.datapackage import DataPackage
from smo_ap_bridge.protocol import ItemKind
from smo_ap_bridge.repl import parse_command
from smo_ap_bridge.state import BridgeState


# Resolve the in-repo apworld data dir so tests use the real categories.
_APWORLD = Path(__file__).resolve().parents[2] / "apworld" / "smo_archipelago" / "data"


@pytest.fixture
def dp() -> DataPackage:
    assert _APWORLD.exists(), f"apworld data missing: {_APWORLD}"
    return DataPackage(apworld_data_dir=_APWORLD)


@pytest.fixture
def state() -> BridgeState:
    return BridgeState()


def test_empty_line_is_noop(dp, state):
    r = parse_command("", dp, state)
    assert r.item is None and r.error is None and r.info is None and not r.quit


def test_whitespace_only_is_noop(dp, state):
    r = parse_command("   \t  ", dp, state)
    assert r.item is None and r.error is None


def test_help_command(dp, state):
    r = parse_command("help", dp, state)
    assert r.info is not None and "grant" in r.info and "capture" in r.info
    assert r.item is None


def test_help_alias_h(dp, state):
    r = parse_command("h", dp, state)
    assert r.info is not None and "grant" in r.info


def test_quit(dp, state):
    assert parse_command("quit", dp, state).quit
    assert parse_command("exit", dp, state).quit
    assert parse_command("q", dp, state).quit
    assert parse_command("QUIT", dp, state).quit  # case-insensitive command


def test_unknown_command(dp, state):
    r = parse_command("foobar arg", dp, state)
    assert r.error is not None and "foobar" in r.error
    assert r.item is None


def test_grant_kingdom_specific_power_moon(dp, state):
    r = parse_command("grant Cascade Kingdom Power Moon", dp, state)
    assert r.error is None, r.error
    assert r.item is not None
    assert r.item.kind == "moon"
    assert r.item.kingdom == "Cascade"
    assert r.item.shine_id == "Power Moon"
    assert r.item.from_ == "repl"


def test_grant_generic_power_moon(dp, state):
    """The truly-generic 'Power Moon' item has no kingdom prefix."""
    r = parse_command("grant Power Moon", dp, state)
    assert r.error is None, r.error
    assert r.item is not None
    assert r.item.kind == "moon"
    # Bridge classifier returns kingdom=None for genericmoon items.
    assert r.item.kingdom is None
    assert r.item.shine_id == "Power Moon"


def test_grant_kingdom_multi_moon(dp, state):
    r = parse_command("grant Cascade Kingdom Multi-Moon", dp, state)
    assert r.error is None
    assert r.item is not None
    assert r.item.kingdom == "Cascade"
    assert r.item.shine_id == "Multi-Moon"


def test_grant_no_arg(dp, state):
    r = parse_command("grant", dp, state)
    assert r.error is not None and "usage" in r.error


def test_grant_non_moon_item_rejected(dp, state):
    """`grant` is moon-only; use `capture`/`kingdom` for those."""
    r = parse_command("grant Goomba", dp, state)
    # "Goomba" classifies as CAPTURE (it's in items.json with the Capture category),
    # so grant rejects it with a hint.
    assert r.error is not None and "moon" in r.error


def test_capture_command(dp, state):
    r = parse_command("capture Goomba", dp, state)
    assert r.error is None
    assert r.item is not None
    assert r.item.kind == "capture"
    assert r.item.cap == "Goomba"
    assert r.item.from_ == "repl"


def test_capture_no_arg(dp, state):
    r = parse_command("capture", dp, state)
    assert r.error is not None and "usage" in r.error


def test_kingdom_command(dp, state):
    r = parse_command("kingdom Sand", dp, state)
    assert r.error is None
    assert r.item is not None
    assert r.item.kind == "kingdom"
    assert r.item.kingdom == "Sand"
    assert r.item.from_ == "repl"


def test_kingdom_no_arg(dp, state):
    r = parse_command("kingdom", dp, state)
    assert r.error is not None and "usage" in r.error


def test_status_empty_state(dp, state):
    r = parse_command("status", dp, state)
    assert r.info is not None
    assert "received_items=0" in r.info
    assert "checked_locations=0" in r.info


def test_status_after_received_item(dp, state):
    # Inject a moon item directly into state to simulate prior REPL activity.
    from smo_ap_bridge.protocol import ItemRef
    from smo_ap_bridge.state import ItemEvent

    state.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        sender="repl",
    ))
    r = parse_command("status", dp, state)
    assert "received_items=1" in r.info
    assert "Cap=1" in r.info
    assert "Power Moon" in r.info
