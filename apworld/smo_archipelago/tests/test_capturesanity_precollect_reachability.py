"""Real-logic regression guard for the capturesanity precollect fix (T4).

Mirrors test_abilitysanity_precollect_reachability.py. Why this exists:
`capturesanity: false` used to drop capture LOCATIONS only
(before_is_location_enabled) -- the capture ITEMS still rode the pool, so
Devon found a moon holding Jizo with capturesanity off (2026-07-09; P5 doc
§6.5). This file builds a real multiworld with capturesanity off and asserts
the item pool has zero Capture-category items AND that every Capture name is
precollected at its UNLOCK count (1 per capture) -- with the 3 fixed + 1
random starter captures (already precollected by _precollect_starting_captures)
counted once, not twice. Precollecting a capture's full items.json count would
include the pool-only clone copies, minting spurious duplicate->coin grants on
every boot (the sanity-OFF coin bug, 2026-07-11).

Gated on SMOAP_LIVE_AP=1 like the other tests that need vendor/Archipelago +
its deps (the suite's conftest deliberately keeps Archipelago off sys.path).
Run via a subprocess so importing AutoWorldRegister doesn't pollute the parent
process / collide the loose source with the installed zip.

    SMOAP_LIVE_AP=1 .venv/Scripts/python -m pytest -v \
        apworld/smo_archipelago/tests/test_capturesanity_precollect_reachability.py

NOTE: exercises the INSTALLED meatballs.apworld zip (AutoWorldRegister loads
the zip, not the loose source). Run scripts/install_apworld.py first if
you've edited hooks/World.py -- otherwise this validates the previously
installed behavior.
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
    reason="set SMOAP_LIVE_AP=1 to run the capturesanity precollect regression "
           "(requires vendor/Archipelago checkout + AP pip deps installed)",
)

# Standalone probe: prints a single RESULT line the test parses. Kept inline so
# there's no extra committed script to drift out of sync.
_PROBE = r"""
import sys, os
from collections import Counter
AP = sys.argv[1]
sys.path.insert(0, AP); os.chdir(AP)
from worlds.AutoWorld import AutoWorldRegister
from test.general import setup_multiworld

wt = next((w for w in AutoWorldRegister.world_types.values()
           if w.game == "Spicy Meatball Overdrive"), None)
assert wt, "Spicy Meatball Overdrive not registered (install meatballs.apworld?)"

# capturesanity explicitly off, the combo that left Jizo placeable in the pool.
mw = setup_multiworld(
    wt, steps=("generate_early", "create_regions", "create_items"),
    options={"capturesanity": False}, seed=1,
)
p = 1
world = mw.worlds[p]

pool_has_capture = any(
    "Capture" in world.item_name_to_item.get(it.name, {}).get("category", [])
    for it in mw.itempool
)

precollected_counts = Counter(it.name for it in mw.precollected_items[p])
capture_names = sorted(
    name for name, data in world.item_name_to_item.items()
    if "Capture" in data.get("category", [])
)
from worlds.meatballs.client.abilities import unlock_count
mismatches = []
for name in capture_names:
    # Each capture unlocks on its first copy (unlock_count == 1); the clone
    # copies some captures carry in items.json are pool-only and must NOT be
    # precollected (they'd mint spurious dup-coin grants every boot).
    count = int(world.item_name_to_item[name].get("count", 1))
    expected = min(count, unlock_count(name))
    got = precollected_counts.get(name, 0)
    if got != expected:
        mismatches.append(f"{name}:{got}!={expected}")

print(
    "RESULT "
    f"pool_has_capture={int(pool_has_capture)} "
    f"mismatches={('|'.join(mismatches)) if mismatches else 'NONE'}"
)
"""


def _run_probe() -> dict:
    res = subprocess.run(
        [sys.executable, "-c", _PROBE, str(AP_ROOT)],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
    )
    lines = [l for l in res.stdout.splitlines() if l.startswith("RESULT ")]
    if not lines:
        pytest.fail(f"probe produced no RESULT line\n--- stdout ---\n{res.stdout}\n"
                    f"--- stderr ---\n{res.stderr}")
    out: dict = {}
    for line in lines:
        parts = line.split(" ", 2)[1:]
        for kv in parts:
            k, _, v = kv.partition("=")
            out[k] = v
    return out


def test_capturesanity_off_drops_pool_and_precollects_unlock_counts():
    r = _run_probe()
    assert int(r["pool_has_capture"]) == 0, (
        "capturesanity=false must still drop every Capture item from the "
        "pool (precollect is in addition to the drop, not instead of it)"
    )
    assert r["mismatches"] == "NONE", (
        "every Capture name must be precollected at its UNLOCK count (1, "
        "starters counted once, not twice) -- NOT its full items.json copy "
        "count, which would precollect pool-only clones into spurious dup-coin "
        f"grants; mismatches: {r['mismatches']}"
    )
