"""In-game-reachability regression guard for the Lost/Cloud RE-ARRIVAL gates.

Sibling of test_cascade_reachability.py, for docs/handoff-region-gating-egress.md
item 1. `LostPeace`/`CloudPeace` were `canReachRegion("Night Metro")`, which the
Manual region engine (egress: a region's `requires` gates its OUTGOING entrances)
flips True one kingdom EARLY — Night Metro is reached via the Lost->Night Metro
edge that inherits LOST's requires {KingdomMoons(Wooded,16)}, so the region opens
at the Wooded leave-gate with ZERO Lost moons (empirically: see the audit probe).
Both were repointed to KingdomMoons("Lost",10) so the Lost/Cloud re-arrival moons
gate at the faithful Lost leave-threshold instead.

This builds a real solo multiworld and asserts the three pure-predicate
re-arrival moons (no extra ability/capture clause in their `requires`) are:
  - unreachable with the full prerequisite chain but ZERO Lost moons,
  - still closed at the rolled Lost gate minus one (boundary),
  - all reachable at exactly the rolled Lost gate.

Lost-region locations also inherit Lost's own region requires
{KingdomMoons(Wooded,16)} ANDed at the location level, so the prerequisite chain
collects the full Cascade/Sand/Lake/Wooded pools; the BINDING (latest) gate is
then the Lost leave-count. Cloud is region-reachable only after the same chain
(through Night Metro) plus the Night Metro->Cloud edge KingdomMoons(Lost,10), so
it opens at the same Lost threshold.

Gated on SMOAP_LIVE_AP=1; exercises the INSTALLED meatballs.apworld zip (run
scripts/install_apworld.py first after editing hooks/Rules.py).

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_rearrival_reachability.py
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
    reason="set SMOAP_LIVE_AP=1 to run the re-arrival reachability regression "
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

opts = {"accessibility": "full", "entrance_shuffle": False, "capturesanity": True,
        "abilitysanity": True, "randomize_kingdom_gates": True, "multi_moon_shuffle": True}
mw = setup_multiworld(wt, options=opts, seed=12345)
p = 1
world = mw.worlds[p]
counts = world.get_item_counts()
gate = getattr(world, "rolled_kingdom_gates", {}).get("Lost", 10)

# Pure-predicate re-arrival moons: requires is exactly {LostPeace()}/{CloudPeace()}
# with no extra ability/capture clause, so they isolate the gate under test.
SAMPLE = ["Lost: Stretch and Traverse the Jungle",
          "Lost: Aglow in the Jungle",
          "Cloud: Peach in the Cloud Kingdom"]

def chain(lost_n):
    st = CollectionState(mw)
    for k in ["Cascade", "Sand", "Lake", "Wooded"]:
        for name in (k + " Kingdom Power Moon", k + " Kingdom Multi-Moon"):
            for _ in range(counts.get(name, 0)):
                st.collect(world.create_item(name), prevent_sweep=True)
    for _ in range(lost_n):
        st.collect(world.create_item("Lost Kingdom Power Moon"), prevent_sweep=True)
    return st

def n_reach(st):
    return sum(1 for m in SAMPLE if st.can_reach_location(m, p))

zero = n_reach(chain(0))
below = n_reach(chain(max(0, gate - 1)))
full = n_reach(chain(gate))
print(f"RESULT gate={gate} zero={zero} below={below} full={full} total={len(SAMPLE)}")
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


def test_rearrival_moons_gated_by_lost_leave_threshold():
    r = _run_probe()
    total, gate = int(r["total"]), int(r["gate"])
    # The off-by-one regression: re-arrival moons reachable one kingdom early
    # (at the Wooded gate, zero Lost moons) — canReachRegion("Night Metro") again.
    assert int(r["zero"]) == 0, (
        f"Lost/Cloud re-arrival moons reachable with ZERO Lost moons "
        f"({r['zero']}/{total}) — LostPeace/CloudPeace gating one kingdom early "
        f"(canReachRegion of Night Metro?).")
    # Boundary: one below the rolled Lost gate stays closed.
    assert int(r["below"]) == 0, (
        f"re-arrival moons opened at Lost gate-1 ({r['below']}/{total}, gate={gate}).")
    # Opens at exactly the rolled Lost leave-gate.
    assert int(r["full"]) == total, (
        f"re-arrival moons NOT all reachable after {gate} Lost Power Moons "
        f"({r['full']}/{total}).")
