"""P3d — decoupled entrance-shuffle region wiring (port graph -> AP regions).

Real-generation probes in the test_cascade_reachability.py style: build a solo
multiworld with `entrance_shuffle=decoupled` (readiness flag flipped inside the
probe — the player-facing OptionError stays live, see PORT_SHUFFLE_SHIPPABLE in
hooks/World.py) and assert the wired region graph's invariants:

  * generation completes and every pooled subarea's interior region is
    reachable under a god state (all items collected);
  * per-direction gating: interior mouths with a Mini-Rocket exit cost are NOT
    traversable without the rocket, ARE with it; nothing over-blocks under god;
  * fixed points wire no entrance EXCEPT the lone-overworld vanilla credit;
  * kingdoms gain Arrival regions (chain channel) whose flight-verification
    edge carries the Manual core's fullRegionCheck (the honest flight-arrival
    predicate), while every regions.json flight edge stays clobber-owned
    (i.e. untouched by the decoupled wiring);
  * same seed => identical wiring (determinism);
  * simple mode grows NO decoupled machinery (byte-identical-behavior guard —
    the full suite is the real regression gate).

Gated on SMOAP_LIVE_AP=1 and run via subprocess like the other live tests.
NOTE: exercises the INSTALLED meatballs.apworld zip — run
`python scripts/install_apworld.py` after editing hooks/World.py or
port_graph.py, or these validate stale code.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_decoupled_region_wiring.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
AP_ROOT = REPO / "vendor" / "Archipelago"

pytestmark = pytest.mark.skipif(
    os.environ.get("SMOAP_LIVE_AP") != "1",
    reason="set SMOAP_LIVE_AP=1 to run the decoupled region-wiring probes "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

# Shared probe prelude: flip the readiness flag, register the world, define
# helpers. The flag flip must happen before setup_multiworld (the OptionError
# raise runs in before_create_regions).
_PRELUDE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from BaseClasses import CollectionState
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

import worlds.meatballs.hooks.World as WorldHooks
WorldHooks.PORT_SHUFFLE_SHIPPABLE = True  # test-only readiness flip (P3d)

from worlds.meatballs.port_graph import INTERIOR, OVERWORLD, mouth_cost
from worlds.meatballs.entrance_logic import SUBAREA_EXIT_GATES

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

OPTS = {"accessibility": "full", "entrance_shuffle": "decoupled",
        "capturesanity": True, "abilitysanity": True,
        "randomize_kingdom_gates": True, "multi_moon_shuffle": True}

def build(seed, opts=None):
    mw = setup_multiworld(wt, options=(opts or OPTS), seed=seed)
    return mw, mw.worlds[1]

def god_state(mw):
    st = CollectionState(mw)
    for item in mw.itempool:
        st.collect(item, prevent_sweep=True)
    return st

def port_entrances(mw, p=1):
    return [e for e in mw.get_entrances() if e.player == p and " => " in e.name]
"""

# Main wiring probe: one RESULT line per seed. Seeds are fixed so the rolled
# fixed-point shapes are deterministic; between them both shapes (lone
# overworld / lone interior) must occur — asserted by the test, so a shape
# drift after a data regen fails loudly instead of silently un-covering one.
# (Shapes as of 2026-07: seed 1 -> lone interior
# CapWorldHomeStage#PushBlockExStageEntDokan, seeds 11/22 -> lone overworld.)
_PROBE_WIRING = _PRELUDE + r"""
for seed in (1, 11, 22):
    mw, world = build(seed)
    p = 1
    graph, matching = world._port_graph, world._port_matching
    pooled = sorted({m.subarea for m in graph.mouths.values()})

    god = god_state(mw)
    unreachable = [s for s in pooled
                   if not god.can_reach(f"{s} Interior", "Region", p)]

    empty = CollectionState(mw)
    has_rocket = int(empty.has("Mini Rocket", p))

    ents = {e.name: e for e in port_entrances(mw)}

    # Fixed points: exactly one entrance-less shape allowed, except the
    # lone-overworld credit edge.
    fixed = [k for k, v in matching.items() if k == v]
    fp_ow = fp_int = credit_ok = fp_bad = 0
    for fp in fixed:
        m = graph.mouths[fp]
        edges_from_fp = [n for n in ents if n.startswith(f"{fp} => ")]
        if m.side == OVERWORLD and graph.vanilla_matching.get(fp) == fp:
            fp_ow += 1
            want = f"{fp} => {m.subarea} Interior (vanilla credit)"
            if edges_from_fp == [want]:
                credit_ok += 1
        else:
            fp_int += 1
            if edges_from_fp:
                fp_bad += 1

    # Pair edges: both directions present; per-direction Mini-Rocket gating;
    # no god-state over-block anywhere.
    missing_dir = overblocked = rocket_edges = rocket_blocked = rocket_god = 0
    for a_id, b_id in matching.items():
        if a_id == b_id:
            continue
        name = f"{a_id} => {b_id}"
        e = ents.get(name)
        if e is None:
            missing_dir += 1
            continue
        if not e.access_rule(god):
            overblocked += 1
        a = graph.mouths[a_id]
        if a.side == INTERIOR and a.subarea in SUBAREA_EXIT_GATES:
            rocket_edges += 1
            if not e.access_rule(empty):
                rocket_blocked += 1
            if e.access_rule(god):
                rocket_god += 1

    # Arrival regions: flight edge clobber-owned, presence edge free, and
    # every exit of a regions.json kingdom region still carries the core
    # fullRegionCheck (flight gates unchanged / nothing of ours overwrote it).
    arrivals = getattr(world, "_port_arrival_regions", [])
    flight_ok = back_ok = 0
    for k in arrivals:
        fe = mw.get_entrance(f"{k} -> {k} Arrival", p)
        if getattr(fe.access_rule, "__qualname__", "") == "set_rules.<locals>.fullRegionCheck":
            flight_ok += 1
        be = mw.get_entrance(f"{k} Arrival -> {k}", p)
        if be.access_rule(empty):
            back_ok += 1
    from worlds.meatballs.entrance_logic import load_data_json
    region_names = list(load_data_json("regions.json"))
    unclobbered_kingdom_exits = 0
    for rn in region_names:
        try:
            reg = mw.get_region(rn, p)
        except Exception:
            continue
        for e in reg.exits:
            if getattr(e.access_rule, "__qualname__", "") != "set_rules.<locals>.fullRegionCheck":
                unclobbered_kingdom_exits += 1

    chain_into_arrival = sum(
        1 for e in port_entrances(mw)
        if e.connected_region is not None
        and e.connected_region.name.endswith(" Arrival"))

    print(f"RESULT seed={seed} pooled={len(pooled)} unreachable={len(unreachable)} "
          f"fp_ow={fp_ow} fp_int={fp_int} credit_ok={credit_ok} fp_bad={fp_bad} "
          f"missing_dir={missing_dir} overblocked={overblocked} "
          f"rocket_edges={rocket_edges} rocket_blocked={rocket_blocked} "
          f"rocket_god={rocket_god} has_rocket={has_rocket} "
          f"arrivals={len(arrivals)} flight_ok={flight_ok} back_ok={back_ok} "
          f"unclobbered={unclobbered_kingdom_exits} chain_in={chain_into_arrival}")
    if unreachable:
        print("UNREACHABLE " + "|".join(unreachable))
"""

# Determinism probe: same seed twice => identical matching and entrance set.
_PROBE_DETERMINISM = _PRELUDE + r"""
mw1, w1 = build(11)
mw2, w2 = build(11)
same_matching = int(w1._port_matching == w2._port_matching)
names1 = sorted(e.name for e in port_entrances(mw1))
names2 = sorted(e.name for e in port_entrances(mw2))
mw3, w3 = build(12)
differs = int(w1._port_matching != w3._port_matching)
print(f"RESULT same_matching={same_matching} same_entrances={int(names1 == names2)} "
      f"edges={len(names1)} distinct_seed_differs={differs}")
"""

# Simple-mode guard: no decoupled machinery may grow under simple (off is
# covered by the same assertion path — neither sets _port_matching).
_PROBE_SIMPLE_GUARD = _PRELUDE + r"""
mw, world = build(11, opts={"accessibility": "full", "entrance_shuffle": "simple",
                            "capturesanity": True, "abilitysanity": True})
has_port = int(getattr(world, "_port_matching", None) is not None)
arrival_regions = [r.name for r in mw.get_regions(1) if r.name.endswith(" Arrival")]
port_edges = len(port_entrances(mw))
print(f"RESULT has_port={has_port} arrival_regions={len(arrival_regions)} "
      f"port_edges={port_edges}")
"""


def _run_probe(probe: str, prefix: str = "RESULT") -> list[dict]:
    res = subprocess.run(
        [sys.executable, "-c", probe, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith(prefix + " ")]
    if not lines:
        pytest.fail(f"probe produced no {prefix} line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    return [dict(kv.split("=") for kv in line.split()[1:]) for line in lines]


@pytest.fixture(scope="module")
def wiring_results() -> list[dict]:
    return _run_probe(_PROBE_WIRING)


def test_decoupled_generates_and_all_pooled_interiors_reachable(wiring_results):
    """The flag-flipped decoupled seed generates, and a god-state sweep
    reaches every pooled subarea's interior region (the P3c connectivity
    guarantee, carried through the region wiring)."""
    for r in wiring_results:
        assert int(r["pooled"]) > 90, f"seed {r['seed']}: pool suspiciously small"
        assert int(r["unreachable"]) == 0, (
            f"seed {r['seed']}: {r['unreachable']} pooled interior region(s) "
            f"unreachable under god state — wiring dropped/misrouted an edge")


def test_both_directions_wired_and_nothing_overblocks(wiring_results):
    for r in wiring_results:
        assert int(r["missing_dir"]) == 0, (
            f"seed {r['seed']}: {r['missing_dir']} matched direction(s) have "
            f"no entrance object")
        assert int(r["overblocked"]) == 0, (
            f"seed {r['seed']}: {r['overblocked']} port entrance(s) closed "
            f"even under god state — a rule over-blocks (bad requires string "
            f"or peace fn)")


def test_interior_exit_cost_gates_its_own_direction(wiring_results):
    """Per-direction gating (the handoff's named case): a matched edge leaving
    a Mini-Rocket interior is closed without the rocket and open with it."""
    for r in wiring_results:
        edges = int(r["rocket_edges"])
        assert edges > 0, f"seed {r['seed']}: no Mini-Rocket interior edges found"
        assert int(r["rocket_god"]) == edges, (
            f"seed {r['seed']}: {edges - int(r['rocket_god'])}/{edges} rocket "
            f"edges stay closed WITH all items — exit cost over-blocks")
        if not int(r["has_rocket"]):
            assert int(r["rocket_blocked"]) == edges, (
                f"seed {r['seed']}: only {r['rocket_blocked']}/{edges} "
                f"Mini-Rocket interior edges blocked without the rocket — the "
                f"interior mouth's exit cost is not riding its own direction")


def test_fixed_points_wire_only_the_lone_overworld_credit(wiring_results):
    shapes = set()
    for r in wiring_results:
        assert int(r["fp_bad"]) == 0, (
            f"seed {r['seed']}: {r['fp_bad']} non-credit fixed point(s) grew "
            f"an entrance — fixed points must be vanilla passthrough")
        assert int(r["credit_ok"]) == int(r["fp_ow"]), (
            f"seed {r['seed']}: lone-overworld fixed point missing its "
            f"vanilla credit entrance (region(ow) -> region(subarea))")
        if int(r["fp_ow"]):
            shapes.add("ow")
        if int(r["fp_int"]):
            shapes.add("int")
    assert shapes == {"ow", "int"}, (
        f"probe seeds only exercised fixed-point shape(s) {shapes or '{}'} — "
        f"re-tune the seed list so both lone-overworld and lone-interior "
        f"fixed points stay covered")


def test_kingdom_arrival_channel_and_flight_gates_unchanged(wiring_results):
    for r in wiring_results:
        arrivals = int(r["arrivals"])
        assert arrivals >= 8, (
            f"seed {r['seed']}: only {arrivals} kingdom Arrival regions — "
            f"overworld mouths span ~14 kingdoms")
        assert int(r["flight_ok"]) == arrivals, (
            f"seed {r['seed']}: {arrivals - int(r['flight_ok'])} flight-"
            f"verification edge(s) lost the core fullRegionCheck (the honest "
            f"flight-arrival rule)")
        assert int(r["back_ok"]) == arrivals, (
            f"seed {r['seed']}: {arrivals - int(r['back_ok'])} 'Arrival -> "
            f"kingdom' presence edge(s) not free")
        assert int(r["unclobbered"]) == 0, (
            f"seed {r['seed']}: {r['unclobbered']} exit(s) of regions.json "
            f"regions carry a non-core rule — the decoupled wiring must never "
            f"touch flight edges (D1: no discount)")
        assert int(r["chain_in"]) > 0, (
            f"seed {r['seed']}: no matched edge lands in an Arrival region — "
            f"the chain channel into kingdoms is missing")


def test_same_seed_same_wiring():
    r = _run_probe(_PROBE_DETERMINISM)[0]
    assert int(r["same_matching"]) == 1, "same seed rolled different matchings"
    assert int(r["same_entrances"]) == 1, "same seed wired different entrances"
    assert int(r["edges"]) > 200, f"suspiciously few port edges: {r['edges']}"
    assert int(r["distinct_seed_differs"]) == 1, (
        "two different seeds rolled the same matching — rng not wired through")


def test_simple_mode_grows_no_decoupled_machinery():
    r = _run_probe(_PROBE_SIMPLE_GUARD)[0]
    assert int(r["has_port"]) == 0, "simple mode set _port_matching"
    assert int(r["arrival_regions"]) == 0, "simple mode created Arrival regions"
    assert int(r["port_edges"]) == 0, "simple mode created port entrances"
