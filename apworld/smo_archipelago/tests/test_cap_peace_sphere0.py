"""Reachability guard for the `start_at_cap_peace` option (docs/handoff-cap-peace-sphere-0.md).

`CapPeace()` normally gates Cap Kingdom's peace / re-arrival moons behind the Cascade
leave-gate (KingdomMoons(Cascade,5)) — on a vanilla run you must leave Cascade before you
can fly back to a peaceful Bonneton. The `start_at_cap_peace` option models the special
save-relocate save that boots directly into post-peace Cap with the Odyssey landed, so the
Cap-peace moons are physically collectable from frame zero. When the option is ON,
`CapPeace()` short-circuits to True and those moons become sphere-0 reachable.

Cap Kingdom's region has no requires / connects gate (regions.json), so a location whose
`requires` is exactly `{CapPeace()}` isolates the predicate under test: its only binding
gate is CapPeace.

This builds two real solo multiworlds and asserts the pure-predicate Cap-peace sample:
  - OFF (default): unreachable with ZERO Cascade moons, reachable at the rolled Cascade gate.
  - ON: reachable with ZERO moons collected at all (sphere 0).

Gated on SMOAP_LIVE_AP=1; exercises the INSTALLED meatballs.apworld zip (run
scripts/install_apworld.py first after editing hooks/Rules.py / hooks/Options.py).

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_cap_peace_sphere0.py
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
    reason="set SMOAP_LIVE_AP=1 to run the Cap-peace sphere-0 reachability guard "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

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

# Pure-predicate Cap-peace moons: requires is exactly {CapPeace()} with no extra
# ability/capture clause, so they isolate the gate under test. include_cap_peace_moons
# is ON by default, so these are in the pool.
SAMPLE = ["Cap: Taxi Flying Through Bonneton",
          "Cap: Next to Glasses Bridge"]

def build(start_at_cap_peace):
    opts = {"accessibility": "full", "entrance_shuffle": False, "capturesanity": True,
            "abilitysanity": True, "randomize_kingdom_gates": True, "multi_moon_shuffle": True,
            "start_at_cap_peace": start_at_cap_peace}
    return setup_multiworld(wt, options=opts, seed=12345)

def cascade_chain(mw, world, counts, cascade_n):
    st = CollectionState(mw)
    for _ in range(cascade_n):
        st.collect(world.create_item("Cascade Kingdom Power Moon"), prevent_sweep=True)
    return st

def n_reach(st, world):
    return sum(1 for m in SAMPLE if st.can_reach_location(m, world.player))

# OFF: gates behind the rolled Cascade leave-count.
mw = build(False); p = 1; world = mw.worlds[p]; counts = world.get_item_counts()
gate = getattr(world, "rolled_kingdom_gates", {}).get("Cascade", 5)
off_zero = n_reach(cascade_chain(mw, world, counts, 0), world)
off_below = n_reach(cascade_chain(mw, world, counts, max(0, gate - 1)), world)
off_full = n_reach(cascade_chain(mw, world, counts, gate), world)

# ON: reachable from sphere 0 with NOTHING collected.
mw2 = build(True); world2 = mw2.worlds[1]
on_empty = n_reach(CollectionState(mw2), world2)

print(f"RESULT total={len(SAMPLE)} gate={gate} "
      f"off_zero={off_zero} off_below={off_below} off_full={off_full} on_empty={on_empty}")
"""


def _run_probe() -> dict:
    res = subprocess.run(
        [sys.executable, "-c", _PROBE, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    line = next((l for l in res.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        pytest.fail(f"probe produced no RESULT line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    return dict(kv.split("=") for kv in line.split()[1:])


def test_cap_peace_sphere0_option():
    r = _run_probe()
    total, gate = int(r["total"]), int(r["gate"])
    # OFF (default): the vanilla Cascade leave-gate behavior is unchanged.
    assert int(r["off_zero"]) == 0, (
        f"Cap-peace moons reachable with ZERO Cascade moons while start_at_cap_peace "
        f"is OFF ({r['off_zero']}/{total}) — CapPeace gate leaked.")
    assert int(r["off_below"]) == 0, (
        f"Cap-peace moons opened at Cascade gate-1 ({r['off_below']}/{total}, gate={gate}).")
    assert int(r["off_full"]) == total, (
        f"Cap-peace moons NOT all reachable after {gate} Cascade moons with the option "
        f"OFF ({r['off_full']}/{total}) — KingdomMoons(Cascade) behavior regressed.")
    # ON: sphere-0 reachable with nothing collected.
    assert int(r["on_empty"]) == total, (
        f"start_at_cap_peace ON did not make all Cap-peace moons sphere-0 reachable "
        f"({r['on_empty']}/{total}).")
