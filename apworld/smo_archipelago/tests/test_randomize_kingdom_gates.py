"""Tests for the randomize_kingdom_gates option.

Roll logic: pure-unit against kingdom_gates.py (AP-free, importable without
vendor/Archipelago — same pattern as talkatoo_order.py / its tests).

Wiring (option registration, KingdomMoons override, demotion handoff,
slot_data): source-parsed from hooks/*.py, mirroring test_kingdom_gates.py,
because hooks/World.py imports AP core and conftest deliberately keeps
Archipelago off sys.path.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from kingdom_gates import (
    GATE_RANDOMIZE_SPREAD,
    pool_gate_capacities,
    roll_kingdom_gates,
)

APWORLD_ROOT = Path(__file__).resolve().parents[1]


def _vanilla_gates() -> dict[str, int]:
    """Ground truth from regions.json (same parse as test_kingdom_gates.py)."""
    regions = json.loads(
        (APWORLD_ROOT / "data" / "regions.json").read_text(encoding="utf-8"))
    pat = re.compile(r"\{KingdomMoons\(([^,]+),\s*(\d+)\)\}")
    out: dict[str, int] = {}
    for cfg in regions.values():
        for k, n in pat.findall(cfg.get("requires", "") or ""):
            out[k.strip()] = int(n)
    return out


def _big_capacities(gates: dict[str, int]) -> dict[str, int]:
    """Capacities large enough that no roll ever clamps."""
    return {k: 10_000 for k in gates}


class _FakeItem:
    def __init__(self, name: str):
        self.name = name


def _pool(kingdom: str, mms: int, pms: int) -> list:
    return ([_FakeItem(f"{kingdom} Kingdom Multi-Moon") for _ in range(mms)]
            + [_FakeItem(f"{kingdom} Kingdom Power Moon") for _ in range(pms)])


# ---------------------------------------------------------------- bounds ----

def test_rolls_stay_within_spread_and_floor():
    gates = _vanilla_gates()
    rng = random.Random(0xC0FFEE)
    for _ in range(200):
        rolled = roll_kingdom_gates(rng, gates, _big_capacities(gates))
        for kingdom, vanilla in gates.items():
            lo = max(1, vanilla - GATE_RANDOMIZE_SPREAD)
            hi = vanilla + GATE_RANDOMIZE_SPREAD
            assert lo <= rolled[kingdom] <= hi, (
                f"{kingdom}: rolled {rolled[kingdom]} outside [{lo}, {hi}]")


def test_total_is_preserved_at_vanilla_124():
    """Spec anchor: per-kingdom gates move ±5 but the grand total stays at
    the vanilla 124 — an easier early gate is paid for elsewhere."""
    gates = _vanilla_gates()
    assert sum(gates.values()) == 124  # spec premise
    rng = random.Random(0xBEEF)
    for _ in range(200):
        rolled = roll_kingdom_gates(rng, gates, _big_capacities(gates))
        assert sum(rolled.values()) == 124, rolled


def test_cascade_can_reach_both_extremes():
    """Cascade (vanilla 5) must be able to roll across 1..10 when the other
    kingdoms absorb the difference."""
    gates = _vanilla_gates()
    assert gates["Cascade"] == 5  # spec premise
    seen = set()
    rng = random.Random(1234)
    for _ in range(500):
        seen.add(roll_kingdom_gates(rng, gates, _big_capacities(gates))["Cascade"])
    assert seen <= set(range(1, 11))
    assert min(seen) <= 2, f"low end never explored: {sorted(seen)}"
    assert max(seen) >= 9, f"high end never explored: {sorted(seen)}"


def test_roll_never_below_one():
    gates = _vanilla_gates()
    rng = random.Random(7)
    for _ in range(200):
        rolled = roll_kingdom_gates(rng, gates, _big_capacities(gates))
        assert all(v >= 1 for v in rolled.values())


# ----------------------------------------------------------- determinism ----

def test_same_seed_same_rolls():
    gates = _vanilla_gates()
    a = roll_kingdom_gates(random.Random(42), gates, _big_capacities(gates))
    b = roll_kingdom_gates(random.Random(42), gates, _big_capacities(gates))
    assert a == b


def test_different_seeds_differ_somewhere():
    gates = _vanilla_gates()
    a = roll_kingdom_gates(random.Random(1), gates, _big_capacities(gates))
    b = roll_kingdom_gates(random.Random(2), gates, _big_capacities(gates))
    assert a != b  # 11 kingdoms x 11-wide ranges: collision ~ never


# -------------------------------------------------------- capacity clamp ----

def test_capacity_pinned_kingdom_freezes_and_shrinks_total():
    # Sand capacity 6 < its lo bound (16 - 5 = 11): frozen at 6, excluded
    # from the walk; the preserved total shrinks by the shortfall (10).
    gates = _vanilla_gates()
    caps = _big_capacities(gates)
    caps["Sand"] = 6
    rng = random.Random(99)
    for _ in range(50):
        rolled = roll_kingdom_gates(rng, gates, caps)
        assert rolled["Sand"] == 6
        assert sum(rolled.values()) == 124 - (16 - 6)


def test_zero_capacity_keeps_unsatisfiable_gate_of_one():
    # Festival-style emptied pool: gate must stay >= 1 (closed), never 0
    # (KingdomMoons treats n <= 0 as "always open").
    gates = _vanilla_gates()
    caps = _big_capacities(gates)
    caps["Snow"] = 0
    rng = random.Random(5)
    for _ in range(50):
        assert roll_kingdom_gates(rng, gates, caps)["Snow"] == 1


def test_capacity_within_window_caps_the_walk():
    # Ruined: capacity 7 sits inside [1, 8] — rolls never exceed 7 and the
    # overall total still holds (no kingdom was frozen).
    gates = _vanilla_gates()
    caps = _big_capacities(gates)
    caps["Ruined"] = 7
    rng = random.Random(11)
    for _ in range(100):
        rolled = roll_kingdom_gates(rng, gates, caps)
        assert 1 <= rolled["Ruined"] <= 7
        assert sum(rolled.values()) == 124


def test_pool_gate_capacities_counts_effective_moons():
    pool = _pool("Cascade", mms=2, pms=4) + _pool("Lake", mms=0, pms=7)
    caps = pool_gate_capacities(pool, ["Cascade", "Lake", "Sand"])
    assert caps["Cascade"] == 3 * 2 + 4
    assert caps["Lake"] == 7
    assert caps["Sand"] == 0


def test_pool_gate_capacities_ignores_other_items():
    pool = _pool("Cascade", mms=1, pms=2) + [_FakeItem("Frog"), _FakeItem("Mario's Cap")]
    caps = pool_gate_capacities(pool, ["Cascade"])
    assert caps["Cascade"] == 5


# ----------------------------------------------------- wire message  --------

def test_kingdom_gates_msg_encodes_entries():
    from client.protocol import KingdomGateEntry, KingdomGatesMsg, encode
    wire = encode(KingdomGatesMsg(entries=[
        KingdomGateEntry(kingdom="Cascade", gate=7),
    ]))
    obj = json.loads(wire.decode("utf-8"))
    assert obj == {"t": "kingdom_gates",
                   "entries": [{"kingdom": "Cascade", "gate": 7}]}


def test_kingdom_gates_msg_translates_bowsers():
    """The one AP->Switch kingdom rename: "Bowser's" -> "Bowser"."""
    from client.protocol import KingdomGateEntry, KingdomGatesMsg, encode
    wire = encode(KingdomGatesMsg(entries=[
        KingdomGateEntry(kingdom="Bowser's", gate=12),
    ]))
    obj = json.loads(wire.decode("utf-8"))
    assert obj["entries"] == [{"kingdom": "Bowser", "gate": 12}]


def test_kingdom_gates_msg_empty_is_clear():
    """Empty entries is meaningful wire traffic (full-overwrite clear)."""
    from client.protocol import KingdomGatesMsg, encode
    obj = json.loads(encode(KingdomGatesMsg()).decode("utf-8"))
    assert obj == {"t": "kingdom_gates", "entries": []}


# ----------------------------------------------- gated-moon progression ----

def test_every_gated_kingdoms_moons_are_progression():
    """KingdomMoons(K, N) rules are satisfied by collecting that kingdom's
    moons — but AP's reachability sweep only ever collects ADVANCEMENT
    items. A gated kingdom whose moon items lack `progression: true` in
    items.json can never satisfy its gate in logic, walling off everything
    behind it (root cause of the Ruined -> Bowser's/Moon fill failures:
    Ruined's 3 Power Moons were unflagged, so any rolled gate above the
    Multi-Moon's 3 was unsatisfiable)."""
    gates = _vanilla_gates()
    items = json.loads(
        (APWORLD_ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    bad = []
    for i in items:
        m = re.match(r"^(.+) Kingdom (Power Moon|Multi-Moon)$", i.get("name", ""))
        if m and m.group(1) in gates and not i.get("progression"):
            bad.append(i["name"])
    assert not bad, (
        f"moon items of GATED kingdoms missing progression flag: {bad}")


# ------------------------------------------------------------ wiring  -------

def _hooks_src(name: str) -> str:
    return (APWORLD_ROOT / "hooks" / name).read_text(encoding="utf-8")


def test_option_registered():
    src = _hooks_src("Options.py")
    assert "class RandomizeKingdomGates(Toggle)" in src
    assert re.search(
        r'options\["randomize_kingdom_gates"\]\s*=\s*RandomizeKingdomGates', src), \
        "randomize_kingdom_gates not registered in before_options_defined"


def test_rules_kingdom_moons_reads_rolled_table():
    src = _hooks_src("Rules.py")
    m = re.search(r"def KingdomMoons\b.*?(?=\ndef )", src, re.DOTALL)
    assert m, "KingdomMoons not found in hooks/Rules.py"
    assert "rolled_kingdom_gates" in m.group(0), \
        "KingdomMoons does not consult world.rolled_kingdom_gates"


def test_world_rolls_before_demotion_and_passes_gates():
    src = _hooks_src("World.py")
    m = re.search(r"def after_create_items\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m, "after_create_items not found in hooks/World.py"
    body = m.group(0)
    roll_pos = body.find("roll_kingdom_gates(")
    demote_pos = body.find("_demote_surplus_kingdom_moons(")
    assert roll_pos != -1, "after_create_items does not roll gates"
    assert demote_pos != -1 and "item_pool, gates" in body, \
        "demotion not handed the (possibly rolled) gates table"
    assert roll_pos < demote_pos, "gates must be rolled before demotion"
    assert "world.rolled_kingdom_gates" in body, \
        "rolled table not stored for Rules/slot_data consumption"


def test_slot_data_ships_kingdom_gates():
    src = _hooks_src("World.py")
    m = re.search(r"def before_fill_slot_data\b.*?(?=\n# |\ndef )", src, re.DOTALL)
    assert m, "before_fill_slot_data not found in hooks/World.py"
    assert 'slot_data["kingdom_gates"]' in m.group(0)
