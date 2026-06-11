"""Pure helpers for the randomize_kingdom_gates option.

AP-free on purpose (mirrors talkatoo_order.py): hooks/World.py imports from
here for generation, and the test suite imports it directly without needing
vendor/Archipelago on sys.path. Keep it that way — no BaseClasses / worlds
imports in this module.

Semantics (per the option's design):
  * Each gated kingdom's leave threshold rolls uniformly in
    [vanilla - GATE_RANDOMIZE_SPREAD, vanilla + GATE_RANDOMIZE_SPREAD].
  * Hard floor of 1 (Cascade's vanilla 5 rolls 1..10 — the spec anchor).
  * Clamped to the pool's effective capacity for that kingdom
    (3 per Multi-Moon + 1 per Power Moon) so a high roll can never exceed
    what the (possibly moon-count-trimmed, possibly festival-emptied) pool
    can satisfy — Rules.KingdomMoons would otherwise emit an unsatisfiable
    rule and generation would fail.
  * Zero-capacity kingdoms (festival goal empties post-Metro pools) keep a
    gate of 1: still unsatisfiable from an empty pool, matching the vanilla
    lockout semantics. Never 0 — KingdomMoons treats n <= 0 as "always open".
"""

from __future__ import annotations

from typing import Iterable, Mapping

GATE_RANDOMIZE_SPREAD = 5


def pool_gate_capacities(item_pool: Iterable,
                         kingdoms: Iterable[str]) -> dict[str, int]:
    """Effective-moon capacity the pool can supply per kingdom.

    `item_pool` is any iterable of objects with a `.name` attribute (AP items
    in production, light fakes in tests). 3 per "<K> Kingdom Multi-Moon",
    1 per "<K> Kingdom Power Moon".
    """
    names = [getattr(it, "name", None) for it in item_pool]
    caps: dict[str, int] = {}
    for kingdom in kingdoms:
        pm_name = f"{kingdom} Kingdom Power Moon"
        mm_name = f"{kingdom} Kingdom Multi-Moon"
        caps[kingdom] = (3 * sum(1 for n in names if n == mm_name)
                         + sum(1 for n in names if n == pm_name))
    return caps


# Transfer-walk steps per kingdom. Enough mixing that any kingdom can reach
# either end of its ±SPREAD range in a single roll; cheap (O(steps) randints).
_WALK_STEPS_PER_KINGDOM = 16


def roll_kingdom_gates(rng, base_gates: Mapping[str, int],
                       capacities: Mapping[str, int]) -> dict[str, int]:
    """Roll each kingdom gate to vanilla ± GATE_RANDOMIZE_SPREAD while
    PRESERVING THE TOTAL (vanilla SMO: 124 across the 11 gated kingdoms).

    Mechanism: a seeded transfer walk. Start at vanilla; repeatedly pick two
    kingdoms and move one moon of requirement from one to the other, only
    when both stay inside their bounds:
      lo = max(1, vanilla - SPREAD)
      hi = min(vanilla + SPREAD, capacity)   (capacity absent = no clamp)
    Every transfer is sum-neutral, so the rolled table always totals
    sum(base_gates) — except for kingdoms whose capacity pins them BELOW
    their lo bound (festival-emptied pools, extreme moon-count floors):
    those are frozen at max(1, capacity), excluded from the walk, and the
    preserved total shrinks by their shortfall. `rng` is anything with
    randint(lo, hi) — the world's seeded random in production.
    """
    lo: dict[str, int] = {}
    hi: dict[str, int] = {}
    value: dict[str, int] = {}
    walkers: list[str] = []
    for kingdom, vanilla in base_gates.items():
        k_lo = max(1, vanilla - GATE_RANDOMIZE_SPREAD)
        k_hi = vanilla + GATE_RANDOMIZE_SPREAD
        cap = capacities.get(kingdom)
        if cap is not None:
            k_hi = min(k_hi, cap)
        if k_hi < k_lo:
            # Capacity-pinned below the roll window: freeze and exclude.
            value[kingdom] = max(1, k_hi)
            continue
        lo[kingdom], hi[kingdom] = k_lo, k_hi
        value[kingdom] = vanilla if k_lo <= vanilla <= k_hi else k_hi
        walkers.append(kingdom)

    if len(walkers) >= 2:
        steps = _WALK_STEPS_PER_KINGDOM * len(walkers)
        for _ in range(steps):
            a = walkers[rng.randint(0, len(walkers) - 1)]
            b = walkers[rng.randint(0, len(walkers) - 1)]
            if a == b:
                continue
            if value[a] < hi[a] and value[b] > lo[b]:
                value[a] += 1
                value[b] -= 1
    return value
