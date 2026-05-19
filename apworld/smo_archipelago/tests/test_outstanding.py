"""Unit tests for M6 phase D — derived per-kingdom outstanding.

Outstanding is no longer mutable state: it's derived as
    outstanding[K] = moons_received_by_kingdom[K] - pay_shine_num_by_kingdom[K]
where lifetime_received comes from add_received_item (AP-server side) and
pay_shine_num comes from PaySnapshotMsg (Switch save side). This file
covers the math + sentinel invariants, and the headline crash-rollback
regression that the refactor exists to prevent.
"""

from __future__ import annotations

from client.protocol import ItemRef
from client.state import BridgeState, ItemEvent


# ---------- apply_pay_snapshot ----------

def test_apply_pay_snapshot_wholesale_replaces():
    """A snapshot is the authoritative PayShineNum reading; we replace
    rather than merge so a kingdom Mario hasn't visited (absent from the
    snapshot) doesn't keep a stale value from a prior snapshot."""
    s = BridgeState()
    s.apply_pay_snapshot({"Cap": 3, "Cascade": 1})
    assert s.get_pay_shine_num() == {"Cap": 3, "Cascade": 1}
    s.apply_pay_snapshot({"Sand": 2})
    assert s.get_pay_shine_num() == {"Sand": 2}


def test_apply_pay_snapshot_clamps_negative():
    """Defensive: a malformed snapshot with a negative pay must not
    poison the derived outstanding (would otherwise add to lifetime)."""
    s = BridgeState()
    s.apply_pay_snapshot({"Cap": -5})
    assert s.get_pay_shine_num() == {"Cap": 0}


# ---------- compute_outstanding ----------

def test_compute_outstanding_returns_none_before_first_snapshot():
    """Sentinel: bridge must NOT push OutstandingMsg until the Switch's
    save is loaded and snapshot has landed. Otherwise the Switch sees a
    spurious lifetime-equivalent on title screen."""
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
    ))
    assert s.compute_outstanding() is None


def test_compute_outstanding_subtracts_pay_from_lifetime():
    s = BridgeState()
    for _ in range(5):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        ))
    s.apply_pay_snapshot({"Cap": 2})
    assert s.compute_outstanding() == {"Cap": 3}


def test_compute_outstanding_clamps_at_zero_when_pay_exceeds_lifetime():
    """Vanilla SMO moons not credited to AP can bump PayShineNum past
    what AP has delivered. Outstanding must clamp at 0, not go negative."""
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
    ))
    s.apply_pay_snapshot({"Cap": 5})
    assert s.compute_outstanding() == {"Cap": 0}


def test_compute_outstanding_includes_unreceived_kingdom_as_zero():
    """A kingdom present only in the pay snapshot (Mario paid moons there
    but never received any AP moons) shows up with outstanding=0 — useful
    for the Switch's zero-out path even when the bridge has nothing to
    grant."""
    s = BridgeState()
    s.apply_pay_snapshot({"Cascade": 3})
    out = s.compute_outstanding()
    assert out == {"Cascade": 0}


def test_compute_outstanding_keeps_kingdoms_independent():
    s = BridgeState()
    for _ in range(2):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        ))
    for _ in range(3):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Wooded", shine_id="Power Moon"),
        ))
    s.apply_pay_snapshot({"Cap": 1, "Wooded": 0})
    assert s.compute_outstanding() == {"Cap": 1, "Wooded": 3}


# ---------- crash-rollback regression (THE bug-class fix) ----------

def test_crash_rollback_recovers_outstanding():
    """Deposit-then-crash invariant. The whole reason this refactor exists.

    Mario tosses moons at the Odyssey; if SMO crashes BEFORE the autosave
    persists, the save reloads at the pre-toss PayShineNum. Pre-refactor,
    the bridge had already persisted the debited balance and that moon was
    permanently lost. Now: a fresh PaySnapshot with the smaller PayShineNum
    re-derives outstanding upward, recovering the unspent credit."""
    s = BridgeState()
    for _ in range(5):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        ))
    # Snapshot 1: Mario tossed 3 of 5 moons.
    s.apply_pay_snapshot({"Cap": 3})
    assert s.compute_outstanding() == {"Cap": 2}
    # Crash + reload: save had PayShineNum=2 (the toss-of-3 never persisted).
    # The fresh snapshot ships the rolled-back value.
    s.apply_pay_snapshot({"Cap": 2})
    assert s.compute_outstanding() == {"Cap": 3}, (
        "outstanding must rebound when PayShineNum rolls back — this is "
        "the deposit-then-crash recovery the derived-state model exists to provide"
    )


def test_crash_rollback_multi_kingdom():
    """Same mechanic across multiple kingdoms in one save rollback."""
    s = BridgeState()
    for _ in range(3):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Cap", shine_id="Power Moon"),
        ))
    for _ in range(4):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Cascade", shine_id="Power Moon"),
        ))
    s.apply_pay_snapshot({"Cap": 2, "Cascade": 3})
    assert s.compute_outstanding() == {"Cap": 1, "Cascade": 1}
    # Crash rollback — Cap stayed at 1, Cascade rolled back to 1.
    s.apply_pay_snapshot({"Cap": 1, "Cascade": 1})
    assert s.compute_outstanding() == {"Cap": 2, "Cascade": 3}


# ---------- get_kingdom_lifetime_received (compute_outstanding input + GUI) ----------
#
# Effective per-kingdom moon counts with Multi-Moon weighted as 3 (matches
# `KingdomMoons` in hooks/Rules.py). One of the two inputs to
# compute_outstanding (the other is PayShineNum from PaySnapshotMsg); also
# read by the Kivy GUI for the per-kingdom recv/need display. M7 Path A's
# kingdom-order gate USED to read this via OutstandingMsg lifetime scalars;
# that gate moved to a Switch-side visited bit + current-kingdom OR-check
# that needs no bridge state — see KingdomOrderGate.cpp.

def test_lifetime_received_starts_at_zero_for_unseen_kingdom():
    s = BridgeState()
    assert s.get_kingdom_lifetime_received("Lake") == 0
    assert s.get_kingdom_lifetime_received("Snow") == 0


def test_lifetime_received_counts_power_moons_as_one_each():
    s = BridgeState()
    for _ in range(3):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Lake", shine_id="Power Moon"),
        ))
    assert s.get_kingdom_lifetime_received("Lake") == 3


def test_lifetime_received_weighs_multi_moon_as_three():
    """Matches `KingdomMoons` in hooks/Rules.py and the Switch's
    moonGrantAmount helper. Used by compute_outstanding (lifetime − pay)
    and by the GUI's per-kingdom recv/need display."""
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Snow", shine_id="Multi-Moon"),
    ))
    assert s.get_kingdom_lifetime_received("Snow") == 3
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="moon", kingdom="Snow", shine_id="Power Moon"),
    ))
    assert s.get_kingdom_lifetime_received("Snow") == 4


def test_lifetime_received_does_not_decay_on_pay_snapshot():
    """Invariant: PaySnapshotMsg (the post-toss re-snapshot) updates
    pay_shine_num_by_kingdom but must NOT touch the lifetime counter.
    Otherwise compute_outstanding would underflow against itself after
    every toss."""
    s = BridgeState()
    for _ in range(8):
        s.add_received_item(ItemEvent(
            item=ItemRef(kind="moon", kingdom="Lake", shine_id="Power Moon"),
        ))
    # Mario fuels Lake's Odyssey to leave (debits via PayShineNum=8 snapshot).
    s.apply_pay_snapshot({"Lake": 8})
    assert s.compute_outstanding().get("Lake", 0) == 0   # balance drained
    assert s.get_kingdom_lifetime_received("Lake") == 8  # lifetime intact



def test_lifetime_received_ignores_non_moon_items():
    """Capture and other items must not show up in the lifetime moon count
    (they don't satisfy KingdomMoons in hooks/Rules.py either)."""
    s = BridgeState()
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="capture", kingdom="Lake", cap="Cheep Cheep"),
    ))
    s.add_received_item(ItemEvent(
        item=ItemRef(kind="other", kingdom="Lake"),
    ))
    assert s.get_kingdom_lifetime_received("Lake") == 0
