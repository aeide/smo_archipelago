"""Tests for ColorsConfig (AP-classification -> palette mapping) and the
BridgeState shine-palette accessors used by the scout-replay path."""

from __future__ import annotations

from client.config import (
    KINGDOM_PALETTE_BASE,
    KINGDOM_PALETTE_ORDER,
    ColorsConfig,
)
from client.state import BridgeState


def test_colors_config_defaults_are_distinct():
    """Defaults must give each non-filler classification a unique palette
    index so they're visually distinguishable out of the box."""
    c = ColorsConfig()
    indices = {c.progression, c.useful, c.trap}
    assert len(indices) == 3
    # Filler (0) is the "no override" sentinel; it's fine for it to share a
    # value with the trap default conceptually, but defaults shouldn't.
    assert c.filler == 0


def test_for_classification_known_values():
    c = ColorsConfig(progression=1, useful=2, trap=3, filler=0)
    assert c.for_classification("progression") == 1
    assert c.for_classification("useful") == 2
    assert c.for_classification("trap") == 3
    assert c.for_classification("filler") == 0


def test_for_classification_unknown_falls_through_to_filler():
    c = ColorsConfig(progression=1, useful=2, trap=3, filler=7)
    assert c.for_classification("") == 7
    assert c.for_classification("bogus") == 7


def test_for_kingdom_maps_to_contiguous_block():
    """Each known kingdom maps to a distinct index in the reserved block
    starting at KINGDOM_PALETTE_BASE, in declared order."""
    c = ColorsConfig()
    for i, kingdom in enumerate(KINGDOM_PALETTE_ORDER):
        assert c.for_kingdom(kingdom) == KINGDOM_PALETTE_BASE + i
    indices = {c.for_kingdom(k) for k in KINGDOM_PALETTE_ORDER}
    assert len(indices) == len(KINGDOM_PALETTE_ORDER)


def test_for_kingdom_includes_cloud_and_dark_sides():
    """Cloud (which the gui visit-order omits) and the Dark/Darker sides must
    still resolve — Cloud grants real moon items; Dark/Darker for completeness."""
    c = ColorsConfig()
    for kingdom in ("Cloud", "Bowser's", "Dark", "Darker"):
        assert c.for_kingdom(kingdom) is not None


def test_for_kingdom_unknown_returns_none():
    """An unknown/empty kingdom yields None so the caller falls back to the
    classification color."""
    c = ColorsConfig()
    assert c.for_kingdom(None) is None
    assert c.for_kingdom("") is None
    assert c.for_kingdom("Atlantis") is None


def test_kingdom_block_does_not_overlap_classification_indices():
    """The kingdom block must start above every default classification index
    so the two ranges never collide on the wire."""
    c = ColorsConfig()
    class_indices = {c.progression, c.useful, c.trap, c.filler}
    assert min(KINGDOM_PALETTE_BASE + i for i in range(len(KINGDOM_PALETTE_ORDER))) > max(class_indices)


def test_state_shine_palette_round_trip():
    s = BridgeState()
    assert s.all_shine_palette() == {}
    s.set_shine_palette({12: 1, 47: 3})
    assert s.all_shine_palette() == {12: 1, 47: 3}


def test_state_shine_palette_replace_not_merge():
    """set_shine_palette replaces the table — each LocationInfo reply is
    the authoritative full picture for the seed."""
    s = BridgeState()
    s.set_shine_palette({12: 1, 47: 3})
    s.set_shine_palette({100: 2})
    assert s.all_shine_palette() == {100: 2}


def test_state_shine_palette_returns_copy():
    """Mutating the returned dict must not affect bridge state."""
    s = BridgeState()
    s.set_shine_palette({1: 1})
    out = s.all_shine_palette()
    out[999] = 999
    assert 999 not in s.all_shine_palette()
