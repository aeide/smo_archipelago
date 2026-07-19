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
    predicate), while every inter-kingdom flight edge carries the core rule AND
    the D1-erratum flight-economy predicate (add_rule combine="and");
  * flight economy (D1 erratum): the victory region (Moon Kingdom) is reachable
    ONLY at the full cumulative kingdom-gate cost — unreachable empty, still
    unreachable with all non-moon progression, and every chain kingdom's moons
    individually binding (docs/handoff-decoupled-flight-economy-fix.md);
  * same seed => identical wiring (determinism);
  * simple mode grows NO decoupled machinery AND leaves regions.json flight
    edges untouched (byte-identical-behavior guard — the full suite is the real
    regression gate).

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
    region_set = set(region_names)
    # D1 erratum fix (_apply_decoupled_flight_economy): every inter-kingdom
    # flight edge (regions.json -> non-exempt regions.json) now carries the core
    # fullRegionCheck AND the flight_reach predicate (add_rule combine="and",
    # whose wrapper qualname is add_rule.<locals>.<lambda>). The
    # "K -> K Arrival" flight-verification edges must STILL be the untouched
    # core fullRegionCheck (Pokino, dest not in regions.json, and Arrival dests
    # are excluded by construction).
    EXEMPT = {"Pokino"}
    flight_edges = flight_edges_econ = 0
    verif_edges = verif_clobbered = 0
    for rn in region_names:
        try:
            reg = mw.get_region(rn, p)
        except Exception:
            continue
        for e in reg.exits:
            dest = e.connected_region.name if e.connected_region is not None else ""
            qn = getattr(e.access_rule, "__qualname__", "")
            if dest in region_set and dest not in EXEMPT:
                flight_edges += 1
                if qn == "add_rule.<locals>.<lambda>":
                    flight_edges_econ += 1
            elif dest.endswith(" Arrival"):
                verif_edges += 1
                if qn == "set_rules.<locals>.fullRegionCheck":
                    verif_clobbered += 1

    chain_into_arrival = sum(
        1 for e in port_entrances(mw)
        if e.connected_region is not None
        and e.connected_region.name.endswith(" Arrival"))

    # One-way far side (Devon 2026-07-08): every pair edge FROM an exit-only
    # interior mouth must source from its subarea's far-side region, the
    # reverse direction must land THERE (not in the full interior), the free
    # course edge full->far must exist for every far region, and no edge may
    # go far->full (the one-way rule itself).
    from worlds.meatballs.port_graph import entry_capable_interior_mouths
    capable = entry_capable_interior_mouths(graph)
    far_regions = {r.name for r in mw.get_regions(p)
                   if r.name.endswith(" Interior (far side)")}
    far_misrouted = far_backflow = far_missing_course = 0
    for a_id, b_id in matching.items():
        if a_id == b_id:
            continue
        a = graph.mouths[a_id]
        if a.side != INTERIOR or a_id in capable:
            continue
        want = f"{a.subarea} Interior (far side)"
        e_out = ents.get(f"{a_id} => {b_id}")
        e_in = ents.get(f"{b_id} => {a_id}")
        if e_out is None or e_out.parent_region.name != want:
            far_misrouted += 1
        if e_in is None or e_in.connected_region.name != want:
            far_misrouted += 1
    for fr in far_regions:
        full = fr[: -len(" (far side)")]
        try:
            ce = mw.get_entrance(f"{full} -> {fr}", p)
            if ce.parent_region.name != full or not ce.access_rule(empty):
                far_missing_course += 1
        except Exception:
            far_missing_course += 1
        far_reg = mw.get_region(fr, p)
        for e in far_reg.exits:
            if e.connected_region is not None and e.connected_region.name == full:
                far_backflow += 1

    print(f"RESULT seed={seed} pooled={len(pooled)} unreachable={len(unreachable)} "
          f"fp_ow={fp_ow} fp_int={fp_int} credit_ok={credit_ok} fp_bad={fp_bad} "
          f"missing_dir={missing_dir} overblocked={overblocked} "
          f"rocket_edges={rocket_edges} rocket_blocked={rocket_blocked} "
          f"rocket_god={rocket_god} has_rocket={has_rocket} "
          f"arrivals={len(arrivals)} flight_ok={flight_ok} back_ok={back_ok} "
          f"flight_edges={flight_edges} flight_edges_econ={flight_edges_econ} "
          f"verif_edges={verif_edges} verif_clobbered={verif_clobbered} "
          f"chain_in={chain_into_arrival} "
          f"far_regions={len(far_regions)} far_misrouted={far_misrouted} "
          f"far_backflow={far_backflow} far_missing_course={far_missing_course}")
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
# Byte-identical guard: the decoupled-only flight-economy predicate must never
# touch a regions.json flight edge under simple — they stay pure fullRegionCheck.
from worlds.meatballs.entrance_logic import load_data_json
region_set = set(load_data_json("regions.json"))
EXEMPT = {"Pokino"}
flight_touched = 0
for rn in region_set:
    try:
        reg = mw.get_region(rn, 1)
    except Exception:
        continue
    for e in reg.exits:
        dest = e.connected_region.name if e.connected_region is not None else ""
        if dest in region_set and dest not in EXEMPT:
            if getattr(e.access_rule, "__qualname__", "") != "set_rules.<locals>.fullRegionCheck":
                flight_touched += 1
print(f"RESULT has_port={has_port} arrival_regions={len(arrival_regions)} "
      f"port_edges={port_edges} flight_touched={flight_touched}")
"""

# Flight-economy invariant (D1 erratum). The behavioral proof that the fix
# restores the cumulative flight moon economy: the victory region (Moon Kingdom)
# — which has no Arrival region, so it is reachable ONLY through the honest
# Bowser's -> Moon flight edge — must cost the full chain of kingdom gates, with
# EVERY chain kingdom's moons individually binding (no discount).
_PROBE_ECONOMY = _PRELUDE + r"""
mw, world = build(1)
p = 1

def is_moon(it):
    return it.name.endswith("Kingdom Power Moon") or it.name.endswith("Kingdom Multi-Moon")

# 1) Empty state -> Moon unreachable (the free-chain leak would flip this True).
empty = CollectionState(mw)
empty_reach = int(empty.can_reach_region("Moon Kingdom", p))

# 2) ALL non-moon progression (abilities + captures + everything not a kingdom
#    moon) -> STILL unreachable: moons are the binding constraint.
nonmoon = CollectionState(mw)
for it in mw.itempool:
    if it.player == p and not is_moon(it):
        nonmoon.collect(it, prevent_sweep=True)
nonmoon_reach = int(nonmoon.can_reach_region("Moon Kingdom", p))

# 3) Full pool -> reachable (nothing over-blocks the honest flight edge).
full = CollectionState(mw)
for it in mw.itempool:
    if it.player == p:
        full.collect(it, prevent_sweep=True)
full_reach = int(full.can_reach_region("Moon Kingdom", p))

# 4) Drop-one-kingdom: for every kingdom whose {KingdomMoons} gate gates
#    reach(Moon), collecting ALL other progression (incl. every OTHER kingdom's
#    moons) but omitting THAT kingdom's moons must leave Moon unreachable — each
#    gate is individually binding, so the economy is never discounted. (Bowser's
#    is excluded: its egress gate is KingdomMoons(Ruined,3), so Bowser's own
#    moons do not gate reach(Moon Kingdom); Moon's own Bowser's,8 gate rides the
#    Moon -> Mushroom edge, not the Bowser's -> Moon arrival.)
CHAIN = ["Cascade","Sand","Wooded","Lake","Lost","Metro","Snow","Seaside","Luncheon","Ruined"]
drop_reachable = []
for k in CHAIN:
    st = CollectionState(mw)
    prefix = k + " Kingdom"
    for it in mw.itempool:
        if it.player != p:
            continue
        if is_moon(it) and it.name.startswith(prefix):
            continue  # omit this kingdom's moons
        st.collect(it, prevent_sweep=True)
    if st.can_reach_region("Moon Kingdom", p):
        drop_reachable.append(k)

print(f"RESULT empty={empty_reach} nonmoon={nonmoon_reach} full={full_reach} "
      f"chain={len(CHAIN)} drop_reachable={len(drop_reachable)}")
if drop_reachable:
    print("DROP " + "|".join(drop_reachable))
"""

# Mushroom route + Arrival-channel purity (2026-07-17, Devon ruling:
# exit-portals are the MK route — docs/handoff-decoupled-mushroom-overworld-
# reachability.md). Two invariants per seed:
#   * ROUTE: "Mushroom Kingdom Arrival" (and hence the MK region) is reachable
#     under god state WITHOUT ever traversing an exit of the Moon Kingdom
#     region — i.e. a real pre-goal chain/portal route exists, never the
#     beat-the-game Moon -> Mushroom win edge (port_matching Mushroom erratum:
#     PeachWorldHomeStage is no longer a connectivity root).
#   * PURITY (the regression the evidence seed's mis-diagnosis feared): every
#     edge into ANY "K Arrival" region is either the single "K -> K Arrival"
#     flight-verification edge or a matched-pair portal edge whose TARGET
#     mouth is an OVERWORLD mouth of K — reaching a subarea interior never
#     grants its home kingdom's overworld through some other edge class. Same
#     check for the Mushroom Kingdom region itself: inbound = its Arrival
#     presence edge + the Moon -> Mushroom flight edge, nothing else.
_PROBE_MUSHROOM = _PRELUDE + r"""
from collections import deque

for seed in (1, 11, 22):
    mw, world = build(seed)
    p = 1
    graph, matching = world._port_graph, world._port_matching
    god = god_state(mw)

    def flood(banned_src_region: str):
        seen = set()
        start = mw.get_region("Menu", p)
        seen.add(start)
        dq = deque([start])
        while dq:
            reg = dq.popleft()
            if reg.name == banned_src_region:
                continue  # never traverse OUT of the banned region
            for e in reg.exits:
                if e.connected_region is None or e.connected_region in seen:
                    continue
                try:
                    ok = e.access_rule(god)
                except Exception:
                    ok = False
                if ok:
                    seen.add(e.connected_region)
                    dq.append(e.connected_region)
        return {r.name for r in seen}

    sans_clear = flood("Moon Kingdom")
    mk_arrival_sans_clear = int("Mushroom Kingdom Arrival" in sans_clear)
    mk_region_sans_clear = int("Mushroom Kingdom" in sans_clear)

    # Arrival-channel purity: classify every inbound edge of every Arrival
    # region (and of the Mushroom Kingdom region itself).
    ow_by_kingdom = {}
    for m in graph.mouths.values():
        if m.side == OVERWORLD:
            ow_by_kingdom.setdefault(m.kingdom, set()).add(m.mouth_id)
    bad_arrival_inbound = 0
    for reg in mw.get_regions(p):
        if not reg.name.endswith(" Arrival"):
            continue
        kingdom = reg.name[: -len(" Arrival")]
        for e in reg.entrances:
            if e.name == f"{kingdom} -> {kingdom} Arrival":
                continue  # flight-verification channel
            if " => " in e.name:
                target_id = e.name.split(" => ")[1]
                if target_id in ow_by_kingdom.get(kingdom, set()):
                    continue  # matched-pair portal onto one of K's own doors
            bad_arrival_inbound += 1
            print(f"BADEDGE seed={seed} arrival={reg.name!r} edge={e.name!r}")
    mk_reg = mw.get_region("Mushroom Kingdom", p)
    mk_inbound = sorted(e.name for e in mk_reg.entrances)
    mk_inbound_ok = int(mk_inbound == sorted([
        "Mushroom Kingdom Arrival -> Mushroom Kingdom",
        "Moon KingdomToMushroom Kingdom"]))
    if not mk_inbound_ok:
        print(f"MKINBOUND seed={seed} edges={mk_inbound}")

    print(f"RESULT seed={seed} mk_arrival_sans_clear={mk_arrival_sans_clear} "
          f"mk_region_sans_clear={mk_region_sans_clear} "
          f"bad_arrival_inbound={bad_arrival_inbound} "
          f"mk_inbound_ok={mk_inbound_ok}")
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


def test_kingdom_arrival_channel_and_flight_economy_predicate(wiring_results):
    """Arrival two-channel shape + the D1 erratum flight-economy predicate.

    Reworked 2026-07-12 (docs/handoff-decoupled-flight-economy-fix.md): the old
    `unclobbered == 0` assertion (every regions.json exit is untouched
    fullRegionCheck) was invalidated by design — the fix ANDs a flight_reach
    predicate onto every inter-kingdom flight edge. The invariant is now:

      * every "K -> K Arrival" flight-verification edge STILL carries the
        untouched core fullRegionCheck (the honest flight-arrival rule) and its
        presence edge is free — the chain channel is unchanged;
      * every inter-kingdom flight edge (regions.json -> non-exempt
        regions.json) carries BOTH the core rule AND the flight predicate
        (add_rule combine="and" wrapper) — the core conjunct survives (add_rule,
        not set_rule) and the predicate is stacked on.
    """
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
        verif = int(r["verif_edges"])
        assert verif == arrivals, (
            f"seed {r['seed']}: {verif} flight-verification edges but {arrivals} "
            f"Arrival regions — expected one 'K -> K Arrival' edge per Arrival")
        assert int(r["verif_clobbered"]) == verif, (
            f"seed {r['seed']}: {verif - int(r['verif_clobbered'])} flight-"
            f"verification edge(s) no longer the untouched core fullRegionCheck "
            f"— the flight-economy predicate must NOT touch the chain channel")
        flight = int(r["flight_edges"])
        assert flight >= 15, (
            f"seed {r['seed']}: only {flight} inter-kingdom flight edges — the "
            f"regions.json DAG has ~18 non-exempt connects_to edges")
        assert int(r["flight_edges_econ"]) == flight, (
            f"seed {r['seed']}: only {r['flight_edges_econ']}/{flight} inter-"
            f"kingdom flight edges carry the flight-economy predicate on top of "
            f"the core rule (D1 erratum: chain arrival must not discount the "
            f"cumulative flight economy)")
        assert int(r["chain_in"]) > 0, (
            f"seed {r['seed']}: no matched edge lands in an Arrival region — "
            f"the chain channel into kingdoms is missing")


def test_one_way_far_side_wiring(wiring_results):
    """One-way course rule (Devon 2026-07-08): exit-only interior mouths must
    route through their subarea's 'Interior (far side)' region — outbound pair
    edges source from it, inbound pair edges land in it, the free full->far
    course edge exists, and nothing flows far->full."""
    for r in wiring_results:
        assert int(r["far_misrouted"]) == 0, (
            f"seed {r['seed']}: {r['far_misrouted']} pair edge(s) of exit-only "
            f"interior mouths wired to the full interior instead of the "
            f"far-side region")
        assert int(r["far_backflow"]) == 0, (
            f"seed {r['seed']}: {r['far_backflow']} far->full edge(s) — the "
            f"one-way rule (cannot reach a course's entrance from its exit) "
            f"is violated in the region graph")
        assert int(r["far_missing_course"]) == 0, (
            f"seed {r['seed']}: {r['far_missing_course']} far-side region(s) "
            f"missing the free full->far course traversal edge")


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
    assert int(r["flight_touched"]) == 0, (
        f"{r['flight_touched']} regions.json flight edge(s) carry a non-core "
        f"rule under SIMPLE — the decoupled-only flight-economy predicate leaked "
        f"outside the decoupled branch (off/simple must be byte-identical)")


def test_decoupled_flight_economy_restores_moon_gate():
    """D1 erratum behavioral invariant (docs/handoff-decoupled-flight-economy-fix.md).

    Before the fix the free 'K Arrival -> K' presence edge let chain arrival
    grant kingdoms without flying the chain, so reach(Moon Kingdom) collapsed to
    ~one kingdom's gate — decoupled seeds beat the goal in ~8 spheres. After the
    fix the victory region costs the full cumulative economy again:

      * empty state -> Moon unreachable (would be True under the leak);
      * ALL non-moon progression -> still unreachable (moons are binding);
      * full pool -> reachable (no over-block);
      * omitting ANY single chain kingdom's moons -> unreachable (every gate is
        individually binding, so nothing is discounted)."""
    r = _run_probe(_PROBE_ECONOMY)[0]
    assert int(r["empty"]) == 0, (
        "Moon Kingdom reachable with an EMPTY collection state — the free "
        "Arrival->K chain still discounts the flight economy (fix not applied?)")
    assert int(r["nonmoon"]) == 0, (
        "Moon Kingdom reachable with ALL non-moon progression but zero kingdom "
        "moons — the cumulative {KingdomMoons} economy is not the binding "
        "constraint on the goal")
    assert int(r["full"]) == 1, (
        "Moon Kingdom UNreachable even with the full item pool — the flight-"
        "economy predicate over-blocks the honest Bowser's->Moon edge")
    assert int(r["drop_reachable"]) == 0, (
        f"omitting one chain kingdom's moons still left Moon reachable "
        f"({r['drop_reachable']}/{r['chain']} kingdom(s)) — that kingdom's gate "
        f"is being discounted (the flight chain is not fully required)")


@pytest.fixture(scope="module")
def mushroom_results() -> list[dict]:
    return _run_probe(_PROBE_MUSHROOM)


def test_mushroom_route_exists_without_game_clear(mushroom_results):
    """Devon ruling 2026-07-17 (exit-portals are the MK route): every decoupled
    seed must reach 'Mushroom Kingdom Arrival' — and through it the MK region —
    under god state WITHOUT traversing any exit of the Moon Kingdom region.
    The route is a chain of matched-pair portals ending in an 'interior exit
    mouth => MK door' hop; the port_matching Mushroom erratum (PeachWorld
    stages are not connectivity roots) makes the roller guarantee one."""
    for r in mushroom_results:
        assert int(r["mk_arrival_sans_clear"]) == 1, (
            f"seed {r['seed']}: no route to Mushroom Kingdom Arrival without "
            f"the beat-the-game Moon->Mushroom edge — the roller's Mushroom "
            f"connectivity guarantee regressed")
        assert int(r["mk_region_sans_clear"]) == 1, (
            f"seed {r['seed']}: MK Arrival reachable but the Mushroom Kingdom "
            f"region is not — the free presence edge is missing/gated")


def test_arrival_inbound_edges_are_portal_or_flight_only(mushroom_results):
    """Regression pinned from the evidence-seed investigation: a kingdom's
    Arrival region may ONLY be entered by (a) its own 'K -> K Arrival'
    flight-verification edge or (b) a matched-pair portal edge targeting one
    of K's own OVERWORLD door mouths. Reaching a subarea interior must never
    grant the home kingdom's overworld by any other edge class (no vanilla
    subarea->home egress edges survive the decoupled rewrite). Ditto the
    Mushroom Kingdom region itself: presence edge + Moon flight edge only."""
    for r in mushroom_results:
        assert int(r["bad_arrival_inbound"]) == 0, (
            f"seed {r['seed']}: {r['bad_arrival_inbound']} non-portal, "
            f"non-flight edge(s) into an Arrival region (see BADEDGE lines)")
        assert int(r["mk_inbound_ok"]) == 1, (
            f"seed {r['seed']}: unexpected inbound edge set on the Mushroom "
            f"Kingdom region (see MKINBOUND line)")
