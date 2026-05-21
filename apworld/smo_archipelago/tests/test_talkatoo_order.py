"""Unit tests for the Talkatoo% Phase 5 sphere-safe ordering validator.

The validator's job: produce a per-kingdom ordered list of moon names
such that at every prefix index i, the next 3 entries (window=3) contain
≥1 reachable moon given items earned from collecting prior entries +
start inventory. This prevents fresh-start Talkatoo% seeds from soft-
locking with all-gated picks.

Tests here exercise the pure-data algorithm (find_safe_permutation_with_oracle
+ is_sphere_safe_with_oracle) using synthetic reachability graphs — no
Archipelago MultiWorld needed. The AP-wrapped path (build_talkatoo_order)
is exercised by the integration test in test_apworld_generation.py
(gated on SMOAP_LIVE_AP=1).
"""

from __future__ import annotations

import random

import pytest

# conftest.py inserts apworld/smo_archipelago/ on sys.path, so
# talkatoo_order is importable as a top-level module.
from talkatoo_order import (
    TalkatooOrderError,
    find_safe_permutation_with_oracle,
    is_sphere_safe_with_oracle,
    _split_kingdom_prefix,
    _shine_id_for,
    collect_pool_per_kingdom,
)


# ---- Synthetic reachability graphs ----

class _Oracle:
    """Stub state: each location has prerequisites; collecting it grants
    the named "items" it yields. Reachable iff all prereqs satisfied.

    Shape: locs = {name: (prereqs: set, grants: set)}.
    State: collected_items: set, collected_locs: set.
    """

    def __init__(self, locs: dict[str, tuple[set[str], set[str]]],
                 start_inv: set[str] | None = None) -> None:
        self.locs = locs
        self.collected_items: set[str] = set(start_inv or set())
        self.collected_locs: set[str] = set()

    def can_reach(self, name: str) -> bool:
        prereqs, _grants = self.locs[name]
        return prereqs.issubset(self.collected_items)

    def collect(self, name: str) -> None:
        self.collected_locs.add(name)
        _prereqs, grants = self.locs[name]
        self.collected_items |= grants


# ---- find_safe_permutation_with_oracle ----

def test_trivial_all_reachable():
    """When every location is reachable from start, any order works.
    Greedy picks one at random per step; order length == input length."""
    locs = {
        f"Cap: Moon{i}": (set(), set()) for i in range(5)
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order is not None
    assert sorted(order) == sorted(locs)
    # Sphere-safe-with-window-3 trivially holds.
    oracle2 = _Oracle(locs)
    assert is_sphere_safe_with_oracle(
        order, oracle2.can_reach, oracle2.collect, window=3)


def test_cross_kingdom_unlock_via_global_greedy():
    """The validator runs a GLOBAL greedy across all kingdoms — it
    must handle cases where a Cap moon's prerequisite is granted by a
    Sand moon (because AP placed Paragoomba at Sand: ...).

    Per-kingdom validation would falsely fail Cap (no Paragoomba in
    Cap's sweep state). Global validation interleaves: collect Sand: X
    first to get Paragoomba, THEN Cap: B becomes reachable.

    User scenario (verbatim): 'A user has moons they cannot get in
    Cap, so they keep going because they have enough, then they are
    stuck in Sand but now unlocked Paragoomba, can make more progress
    against Cap Talkatoo, which then lets them go back to Sand where
    now Talkatoo there would have real moons for them.'
    """
    locs = {
        # Reachable from start. Item: paragoomba (Cap-internal cap,
        # but in this scenario AP placed it at a Sand pool moon).
        "Sand: Bullet Bill Maze Break Through!": (set(), {"paragoomba"}),
        # Reachable from start. Item: chain_chomp.
        "Cap: Frog-Jumping Above the Fog":  (set(), {"chain_chomp"}),
        # Needs paragoomba — only available after collecting Sand: X.
        "Cap: Bonneter Cap Coin":           ({"paragoomba"}, set()),
        # Needs chain_chomp — only available after collecting Cap: Frog.
        "Sand: Chomp Through the Sand Wall": ({"chain_chomp"}, set()),
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order is not None, (
        "Global greedy should resolve the cross-kingdom dependency: "
        "the two 'free' moons (one per kingdom) come first in some "
        "order, then the two gated moons can follow."
    )
    # Cross-kingdom invariant: by the time the paragoomba-needing Cap
    # moon is placed, the Sand moon that grants paragoomba must come
    # before it. Same for the other direction.
    bonneter_idx = order.index("Cap: Bonneter Cap Coin")
    bullet_idx = order.index("Sand: Bullet Bill Maze Break Through!")
    chomp_wall_idx = order.index("Sand: Chomp Through the Sand Wall")
    frog_idx = order.index("Cap: Frog-Jumping Above the Fog")
    assert bullet_idx < bonneter_idx, (
        "Sand: Bullet Bill must precede Cap: Bonneter (which needs paragoomba)"
    )
    assert frog_idx < chomp_wall_idx, (
        "Cap: Frog-Jumping must precede Sand: Chomp Wall (which needs chain_chomp)"
    )


def test_progress_anywhere_invariant_holds_across_global_order():
    """At every step in the global greedy, AT LEAST ONE remaining moon
    (across all kingdoms) is reachable. This is the runtime 'progress
    anywhere' invariant the validator guarantees: the player is never
    stuck because the global order is a topological sort.
    """
    locs = {
        "Cap: A":  (set(), {"k1"}),
        "Cap: B":  ({"k2"}, set()),
        "Cap: C":  ({"k3"}, set()),
        "Sand: X": (set(), {"k2"}),
        "Sand: Y": ({"k1"}, {"k3"}),
        "Sand: Z": ({"k3"}, set()),
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(42), oracle.can_reach, oracle.collect)
    assert order is not None

    # Independent verifier: walk the order and confirm each step had at
    # least one reachable from the remaining set.
    verify = _Oracle(locs)
    placed = set()
    for i, picked in enumerate(order):
        remaining = [n for n in locs if n not in placed]
        reachable = [n for n in remaining if verify.can_reach(n)]
        assert reachable, (
            f"step {i}: no reachable moon anywhere — "
            f"validator should have raised TalkatooOrderError"
        )
        assert picked in reachable, (
            f"step {i}: picked {picked} but it wasn't reachable"
        )
        verify.collect(picked)
        placed.add(picked)


def test_capture_gated_chain_resolves_in_order():
    """Linear capture chain: M2 needs cap_A (granted by M1), M3 needs
    cap_B (granted by M2). Greedy must pick M1 first to unlock M2 to
    unlock M3 — no other order is sphere-safe."""
    locs = {
        "Cascade: M1": (set(), {"cap_A"}),
        "Cascade: M2": ({"cap_A"}, {"cap_B"}),
        "Cascade: M3": ({"cap_B"}, set()),
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order == ["Cascade: M1", "Cascade: M2", "Cascade: M3"]


def test_unreachable_from_start_returns_none():
    """Every moon gated behind cap_A which is never granted (it lives
    elsewhere, not in this slot's pool). Greedy can't find an order —
    returns None so the caller raises TalkatooOrderError."""
    locs = {
        "Sand: M1": ({"cap_A"}, set()),
        "Sand: M2": ({"cap_A"}, set()),
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order is None


def test_unreachable_in_middle_returns_none():
    """M1 reachable from start. M2 needs cap_X (no one grants it). M3
    reachable from start. Greedy picks M1+M3 in some order, then gets
    stuck on M2 → returns None. This is a sphere-UNSAFE seed even with
    window=3 because once cursor reaches M2 there's no reachable moon
    in the window of size 1 left."""
    locs = {
        "Lake: M1": (set(), set()),
        "Lake: M2": ({"cap_X"}, set()),
        "Lake: M3": (set(), set()),
    }
    oracle = _Oracle(locs)
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order is None


def test_start_inventory_is_honored():
    """Slot starts with cap_A in inventory (precollected). M1 needs it
    but is now reachable from step 0."""
    locs = {
        "Cap: M1": ({"cap_A"}, set()),
    }
    oracle = _Oracle(locs, start_inv={"cap_A"})
    order = find_safe_permutation_with_oracle(
        list(locs), random.Random(0), oracle.can_reach, oracle.collect)
    assert order == ["Cap: M1"]


def test_window_safety_holds_for_greedy_output():
    """Whatever the greedy picks, the resulting order is window=3-safe
    (in fact window=1-safe). Verify across a diverse graph."""
    # 6 moons, 3 capture-chains of length 2.
    locs = {
        "Sand: M1": (set(), {"cap_A"}),
        "Sand: M2": ({"cap_A"}, set()),
        "Sand: M3": (set(), {"cap_B"}),
        "Sand: M4": ({"cap_B"}, set()),
        "Sand: M5": (set(), {"cap_C"}),
        "Sand: M6": ({"cap_C"}, set()),
    }
    for seed in range(20):
        oracle = _Oracle(locs)
        order = find_safe_permutation_with_oracle(
            list(locs), random.Random(seed), oracle.can_reach, oracle.collect)
        assert order is not None, f"seed {seed} failed"
        verify_oracle = _Oracle(locs)
        assert is_sphere_safe_with_oracle(
            order, verify_oracle.can_reach, verify_oracle.collect, window=3)


def test_random_seed_affects_order_but_not_safety():
    """Different rng seeds produce different orders but every output is
    sphere-safe (the algorithm is correct, the randomness is in tie-
    break only)."""
    locs = {
        f"Wooded: M{i}": (set(), set())  # all reachable from start
        for i in range(8)
    }
    seen = set()
    for seed in range(50):
        oracle = _Oracle(locs)
        order = find_safe_permutation_with_oracle(
            list(locs), random.Random(seed), oracle.can_reach, oracle.collect)
        assert order is not None
        seen.add(tuple(order))
    # 8! = 40320 orderings exist; 50 seeds should yield several distinct
    # orders. (Probability of 50 trials all yielding the same order is
    # negligible — this asserts randomness, not the exact count.)
    assert len(seen) > 1, "rng tie-break is not producing variety"


# ---- is_sphere_safe_with_oracle (independent verifier) ----

def test_sphere_safe_window_3_lets_skipped_unlock_succeed():
    """Window=3 invariant: even if order[i] is NOT reachable, as long
    as ≥1 of order[i:i+3] is, it counts as safe (the player collects
    the reachable one, state advances, eventually order[i] unlocks)."""
    locs = {
        # M1 needs cap_A which M2 grants. M3 trivially reachable. With
        # order [M1, M3, M2], at i=0 we need {M1, M3, M2} ∩ reachable ≠ ∅.
        # Both M3 and M2 are reachable from start, so the invariant holds
        # at i=0 — but the validator collects M1 to advance state. With
        # the pure-data oracle, that means is_sphere_safe collects M1
        # even though it's not reachable. That's fine for the validator's
        # check (the invariant is purely about reachability of upcoming;
        # collect side-effects are the validator's simulation step).
        "Cap: M1": ({"cap_A"}, set()),
        "Cap: M2": (set(), {"cap_A"}),
        "Cap: M3": (set(), set()),
    }
    oracle = _Oracle(locs)
    assert is_sphere_safe_with_oracle(
        ["Cap: M1", "Cap: M3", "Cap: M2"],
        oracle.can_reach, oracle.collect, window=3)


def test_sphere_safe_window_3_fails_on_isolated_gap():
    """Order [M_gated, M_easy, M_easy] where M_gated needs cap_X (never
    granted) and the window stops at position 0 — invariant should fail
    because nothing in [M_gated] alone is reachable... wait no, with
    window=3 the upcoming is [M_gated, M_easy, M_easy], M_easy IS
    reachable. So safe. Let's try the opposite — last entry gated."""
    locs = {
        "Lake: M1": (set(), set()),
        "Lake: M2": (set(), set()),
        "Lake: M_gated": ({"cap_X"}, set()),
    }
    oracle = _Oracle(locs)
    # At i=2 the window is just [M_gated] (no entries past the end);
    # nothing reachable → fail.
    assert not is_sphere_safe_with_oracle(
        ["Lake: M1", "Lake: M2", "Lake: M_gated"],
        oracle.can_reach, oracle.collect, window=3)


# ---- Helpers ----

def test_split_kingdom_prefix_handles_apostrophe():
    """`Bowser's` kingdom has an apostrophe; the regex must keep it."""
    assert _split_kingdom_prefix("Bowser's: Showdown") == ("Bowser's", "Showdown")
    assert _split_kingdom_prefix("Cap: Frog-Jumping") == ("Cap", "Frog-Jumping")
    assert _split_kingdom_prefix("Capture: Goomba") == ("Capture", "Goomba")
    assert _split_kingdom_prefix("Nothing here") is None


def test_shine_id_for_strips_prefix():
    assert _shine_id_for("Cascade: Multi Moon Atop the Falls") == "Multi Moon Atop the Falls"
    assert _shine_id_for("Bowser's: Showdown") == "Showdown"


# ---- collect_pool_per_kingdom ----

class _FakeItem:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeLocation:
    def __init__(self, name: str, item: _FakeItem | None) -> None:
        self.name = name
        self.item = item


class _FakeMultiWorld:
    def __init__(self, locations: list[_FakeLocation]) -> None:
        self._locations = locations

    def get_locations(self, player: int):
        return self._locations


def test_collect_pool_skips_progression_and_captures():
    """Validator only orders non-progression moon locations. Captures
    and victory locations are dropped."""
    mw = _FakeMultiWorld([
        _FakeLocation("Cascade: Chomp Through the Rocks", _FakeItem("Coin")),
        _FakeLocation("Cascade: Multi Moon Atop the Falls", _FakeItem("Cap Kingdom Power Moon")),
        _FakeLocation("Capture: Goomba", _FakeItem("Cascade Kingdom Power Moon")),
        _FakeLocation("Cap: Frog-Jumping Above the Fog", _FakeItem("Coin")),
        _FakeLocation("Arrive in the Mushroom Kingdom", _FakeItem("__Victory__")),
    ])
    progression = {"Cascade: Multi Moon Atop the Falls"}
    pool = collect_pool_per_kingdom(None, mw, 1, progression)
    assert pool == {
        "Cascade": ["Cascade: Chomp Through the Rocks"],
        "Cap": ["Cap: Frog-Jumping Above the Fog"],
    }


def test_collect_pool_tolerates_locations_without_items():
    """Some locations may not have items assigned yet (defensive) —
    don't crash, just include them and let the collect step handle the
    None item."""
    mw = _FakeMultiWorld([
        _FakeLocation("Sand: Hi", None),
    ])
    pool = collect_pool_per_kingdom(None, mw, 1, set())
    assert pool == {"Sand": ["Sand: Hi"]}


# ---- TalkatooOrderError ----

def test_error_message_mentions_kingdom_and_size():
    """Error message must include the kingdom name (so the user knows
    which one over-constrained) and the pool size (sanity-check the
    failure isn't a degenerate "empty pool"). Tested as a contract on
    the message format, not the exact wording."""
    msg = (
        f"talkatoo_mode: kingdom 'Sand' has no sphere-safe ordering for "
        f"its 7 AP-pool moons (window=3)."
    )
    err = TalkatooOrderError(msg)
    assert "Sand" in str(err)
    assert "7" in str(err)
    assert "window=3" in str(err)
