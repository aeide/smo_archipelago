"""In-game-reachability regression guard for the Cascade scenario gate.

Why this exists: test_scenario_gating.py validates the *compiled fragments*
(`{CascadeDeparture()}` etc. land on the right moons) but never builds a
multiworld, so it cannot catch a gate that is syntactically present yet
semantically a no-op. That is exactly what shipped: `CascadeDeparture()` was
`canReachRegion("Sand Kingdom")`, and because the Manual region engine gates a
region's OUTGOING entrances (egress, not ingress), the Sand region — sitting
right after the free starting Cascade region — is reachable from sphere 0. The
gate evaluated True with zero items, so the bit>=2 Cascade moons (incl. the one
holding Progressive Ground Pound) were "reachable" before leaving Cascade, and
fill stranded the leave-critical moons behind them -> unwinnable starting
kingdom (docs/scenario-logic-revisit-june-20.md §4a).

This test builds a real solo multiworld and asserts, with an EMPTY collection
state, that the Cascade after-ending / moon-rock moons are NOT reachable, and
that they become reachable once the rolled Cascade leave-gate worth of "Cascade
Kingdom Power Moon" items is collected.

Gated on SMOAP_LIVE_AP=1 like the other tests that need vendor/Archipelago +
its deps (the suite's conftest deliberately keeps Archipelago off sys.path).
Run via a subprocess so importing AutoWorldRegister doesn't pollute the parent
process / collide the loose source with the installed zip.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_cascade_reachability.py

NOTE: exercises the INSTALLED meatballs.apworld zip (AutoWorldRegister loads the
zip, not the loose source). Run scripts/install_apworld.py first if you've edited
hooks/Rules.py — otherwise this validates the previously-installed gate.
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
    reason="set SMOAP_LIVE_AP=1 to run the Cascade reachability regression "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

# Standalone probe: prints a single RESULT line the test parses. Kept inline so
# there's no extra committed script to drift out of sync.
_PROBE = r"""
import sys, os
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from BaseClasses import CollectionState
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

opts = {"accessibility": "full", "entrance_shuffle": True, "capturesanity": True,
        "abilitysanity": True, "randomize_kingdom_gates": True, "multi_moon_shuffle": True}
mw = setup_multiworld(wt, options=opts, seed=12345)
p = 1
world = mw.worlds[p]
gate = getattr(world, "rolled_kingdom_gates", {}).get("Cascade", 5)

# Representative bit>=2 (after-ending / moon-rock) Cascade moons that ship a
# {CascadeDeparture()} gate. Must be unreachable with zero items.
DEPARTURE = ["Cascade: Inside the Busted Fossil",
             "Cascade: Next to the Stone Arch",
             "Cascade: Caveman Cave-Fan"]

empty = CollectionState(mw)
reachable_empty = [m for m in DEPARTURE if empty.can_reach_location(m, p)]

# After the rolled gate worth of Cascade Power Moons, they open.
full = CollectionState(mw)
for _ in range(gate):
    full.collect(world.create_item("Cascade Kingdom Power Moon"), prevent_sweep=True)
reachable_full = [m for m in DEPARTURE if full.can_reach_location(m, p)]

# One below the gate: still closed (boundary).
below = CollectionState(mw)
for _ in range(max(0, gate - 1)):
    below.collect(world.create_item("Cascade Kingdom Power Moon"), prevent_sweep=True)
reachable_below = [m for m in DEPARTURE if below.can_reach_location(m, p)]

print(f"RESULT gate={gate} empty={len(reachable_empty)} "
      f"full={len(reachable_full)} below={len(reachable_below)} total={len(DEPARTURE)}")
"""


# Second probe: entrance-shuffle DOOR-side {CascadeDeparture()} gate. Guards the
# regression where (a) the Manual core set_rules overwrote every door entrance's rule
# with its home region's regionCheck (clobbering the door's peace/scenario gate), and
# (b) make_scenario_gate_rule treated CascadeDeparture's requires-STRING return as a
# truthy bool, making the gate a no-op. Net effect: a non-Cascade interior behind a
# post-departure Cascade door (e.g. Mysterious Clouds) — and the Cascade Power Moons
# fill placed inside — were reachable from sphere 0, so the Cascade leave-gate could be
# "satisfied" with moons that actually require leaving and returning.
_PROBE_DOORS = r"""
import sys, os, json
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from BaseClasses import CollectionState
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld
from worlds.meatballs.entrance_logic import load_data_json

wt = next(w for w in AutoWorldRegister.world_types.values()
          if w.game == "Spicy Meatball Overdrive")
opts = {"accessibility": "full", "entrance_shuffle": True, "capturesanity": True,
        "abilitysanity": True, "randomize_kingdom_gates": True, "multi_moon_shuffle": True}
mw = setup_multiworld(wt, options=opts, seed=73191245701192838785)
p = 1
world = mw.worlds[p]
gate = getattr(world, "rolled_kingdom_gates", {}).get("Cascade", 5)
subs = world._entrance_subareas
sg = load_data_json("subarea_scenario_gates.json")

door_entrances = [e for e in mw.get_entrances()
                  if e.player == p and e.name.endswith(" Interior") and " -> " in e.name]
# (a) clobber guard: no door rule may be the core set_rules regionCheck.
clobbered = sum(1 for e in door_entrances
                if getattr(e.access_rule, "__qualname__", "") == "set_rules.<locals>.fullRegionCheck")

# (b) departure-gate guard: doors whose door-subarea members are ALL {CascadeDeparture()}.
empty = CollectionState(mw)
full = CollectionState(mw)
for _ in range(gate):
    full.collect(world.create_item("Cascade Kingdom Power Moon"), prevent_sweep=True)

dep_doors = blocked_empty = open_full = 0
for e in door_entrances:
    door_sub = e.name.split(" -> ")[0]
    members = subs.get(door_sub, {}).get("location_names", [])
    frags = [sg.get(m, "") for m in members]
    if members and all(f == "{CascadeDeparture()}" for f in frags):
        dep_doors += 1
        if not e.access_rule(empty):
            blocked_empty += 1
        if e.access_rule(full):
            open_full += 1

print(f"RESULT2 clobbered={clobbered} dep_doors={dep_doors} "
      f"blocked_empty={blocked_empty} open_full={open_full}")
"""


def _run_probe(probe: str = _PROBE, prefix: str = "RESULT") -> dict:
    res = subprocess.run(
        [sys.executable, "-c", probe, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    line = next((l for l in res.stdout.splitlines() if l.startswith(prefix + " ")), None)
    if line is None:
        pytest.fail(f"probe produced no {prefix} line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    return dict(kv.split("=") for kv in line.split()[1:])


def test_cascade_departure_moons_gated_by_leave_threshold():
    r = _run_probe()
    total, gate = int(r["total"]), int(r["gate"])
    # The no-op regression: every departure moon reachable with zero items.
    assert int(r["empty"]) == 0, (
        f"Cascade after-ending/moon-rock moons reachable with EMPTY state "
        f"({r['empty']}/{total}) — CascadeDeparture is a no-op again "
        f"(canReachRegion of a free region?).")
    # Boundary: one below the gate stays closed.
    assert int(r["below"]) == 0, (
        f"departure moons opened at gate-1 ({r['below']}/{total}, gate={gate}).")
    # Opens at exactly the rolled leave-gate.
    assert int(r["full"]) == total, (
        f"departure moons NOT all reachable after {gate} Cascade Power Moons "
        f"({r['full']}/{total}).")


def test_entrance_shuffle_departure_doors_gate_their_interiors():
    """Under entrance shuffle, a post-departure Cascade door (all members
    {CascadeDeparture()}) must actually gate the interior behind it: blocked with
    empty state, open after the rolled Cascade leave-gate worth of Cascade Power
    Moons. Also asserts no door entrance was left with the core set_rules regionCheck
    (the clobber that dropped every door's peace/scenario gate)."""
    r = _run_probe(_PROBE_DOORS, "RESULT2")
    assert int(r["clobbered"]) == 0, (
        f"{r['clobbered']} door entrance(s) still carry set_rules.fullRegionCheck — "
        f"the door access rules were clobbered by the Manual core set_rules and not "
        f"re-applied (peace + {{CascadeDeparture()}} gates lost).")
    dep = int(r["dep_doors"])
    assert dep > 0, "probe found no all-departure-gated Cascade doors to check"
    assert int(r["blocked_empty"]) == dep, (
        f"only {r['blocked_empty']}/{dep} departure-gated doors blocked with EMPTY "
        f"state — {{CascadeDeparture()}} door gate is a no-op (string-return treated "
        f"as truthy, or rule clobbered).")
    assert int(r["open_full"]) == dep, (
        f"only {r['open_full']}/{dep} departure-gated doors opened after the leave "
        f"gate — the door gate over-blocks.")
